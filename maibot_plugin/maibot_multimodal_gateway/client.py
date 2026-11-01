"""Bounded loopback client. No provider credentials, redirects or retries."""
import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import urllib.error
import urllib.parse
import urllib.request

MAX_REQUEST = 1024 * 1024
MAX_RESPONSE = 48 * 1024 * 1024
PROVIDERS = {'grok': 'grok', 'gpt': 'chatgpt', 'chatgpt': 'chatgpt', 'gemini': 'gemini'}


class GatewayError(RuntimeError):
    def __init__(self, code, status=0):
        self.code, self.status = code, status
        super().__init__(code + (f' (HTTP {status})' if status else ''))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@dataclass(frozen=True)
class Settings:
    base_url: str
    key_file: str
    timeout_seconds: float = 630


def route(provider):
    if provider not in PROVIDERS:
        raise GatewayError('unsupported_provider')
    return PROVIDERS[provider] + '/default'


def text_model(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:grok|chatgpt|gemini)/[A-Za-z0-9._:-]+', value):
        raise GatewayError('invalid_subscription_model')
    return value


def load_key(filename):
    path = Path(filename).expanduser()
    if not filename or not path.is_absolute():
        raise GatewayError('gateway_key_file_required')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
                raise GatewayError('gateway_key_permissions_require_0600')
            raw = source.read(513)
        key = raw.decode('ascii').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,256}', key):
            raise GatewayError('invalid_gateway_key_file')
        return key
    except (OSError, ValueError):
        raise GatewayError('gateway_key_unavailable') from None


class GatewayClient:
    def __init__(self, settings):
        self.settings = settings
        try:
            url = urllib.parse.urlsplit(settings.base_url)
            valid = (url.scheme == 'http' and url.hostname == '127.0.0.1' and
                     url.port is not None and 1 <= url.port <= 65535 and
                     not url.username and not url.password and not url.query and not url.fragment and
                     url.path in ('', '/'))
        except ValueError:
            valid = False
        if not valid:
            raise GatewayError('gateway_requires_ipv4_loopback_origin')
        if not 10 <= settings.timeout_seconds <= 900:
            raise GatewayError('invalid_gateway_timeout')
        self.origin = settings.base_url.rstrip('/')

    def request(self, operation, body=None):
        paths = {'status': '/health', 'chat': '/v1/chat/completions',
                 'image': '/v1/images/generations', 'video': '/v1/videos/generations'}
        if operation not in paths:
            raise GatewayError('unsupported_operation')
        key = load_key(self.settings.key_file)
        payload = None if operation == 'status' else json.dumps(body, ensure_ascii=False).encode()
        if payload is not None and len(payload) > MAX_REQUEST:
            raise GatewayError('request_too_large')
        request = urllib.request.Request(self.origin + paths[operation], data=payload,
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
            method='GET' if payload is None else 'POST')
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
            with opener.open(request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise GatewayError('response_too_large')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise GatewayError('invalid_gateway_response')
            return result
        except urllib.error.HTTPError as error:
            # Do not echo provider bodies or follow a redirect with the key.
            code = {401: 'invalid_gateway_key', 403: 'gateway_permission_denied',
                    429: 'gateway_busy_or_rate_limited', 503: 'gateway_setup_required',
                    504: 'gateway_generation_timeout'}.get(error.code, 'gateway_request_failed')
            status = error.code
            error.close()
            raise GatewayError(code, status) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise GatewayError('gateway_unreachable_or_timeout') from None
        except (ValueError, UnicodeError):
            raise GatewayError('invalid_gateway_response') from None


@dataclass(frozen=True)
class Artifact:
    data: bytes
    encoded: str
    media_type: str
    sha256: str


def artifact(result, kind):
    try:
        items = result['data']
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            raise ValueError()
        item = items[0]
        encoded = item['b64_json']
        limit = 16 * 1024 * 1024 if kind == 'image' else 32 * 1024 * 1024
        if not isinstance(encoded, str) or len(encoded) > ((limit + 2) // 3) * 4:
            raise ValueError()
        data = base64.b64decode(encoded, validate=True)
        mime = ('image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else
                'image/jpeg' if data.startswith(b'\xff\xd8\xff') else
                'image/webp' if data.startswith(b'RIFF') and data[8:12] == b'WEBP' else
                'video/mp4' if data[4:8] == b'ftyp' else None)
        digest = hashlib.sha256(data).hexdigest()
        if (not mime or not mime.startswith(kind + '/') or len(data) > limit or
                item.get('media_type') != mime or type(item.get('bytes')) is not int or
                item['bytes'] != len(data) or item.get('sha256') != digest):
            raise ValueError()
        return Artifact(data, encoded, mime, digest)
    except (KeyError, TypeError, ValueError):
        raise GatewayError('invalid_or_unverified_media') from None


def response_text(result):
    try:
        text = result['choices'][0]['message']['content']
        if not isinstance(text, str) or not text.strip() or len(text) > 64000:
            raise ValueError()
        return text
    except (KeyError, IndexError, TypeError, ValueError):
        raise GatewayError('invalid_gateway_text') from None


def provider_messages(request):
    if request.get('tool_options') or request.get('tool_choice') not in (None, '', 'none'):
        raise GatewayError('provider_tool_calls_not_supported')
    response_format = request.get('response_format')
    if response_format and response_format != {'type': 'text'}:
        raise GatewayError('provider_structured_output_not_supported')
    if 'context_items' in request:
        if request.get('item_schema_version') != 1:
            raise GatewayError('unsupported_context_schema')
        roles = {'SystemMessageItem': 'system', 'UserMessageItem': 'user', 'AssistantMessageItem': 'assistant'}
        items = request['context_items']
        if not isinstance(items, list):
            raise GatewayError('provider_text_messages_only')
        messages = []
        for item in items:
            if not isinstance(item, dict) or item.get('item_type') not in roles:
                raise GatewayError('provider_text_messages_only')
            parts = item.get('parts')
            if not isinstance(parts, list) or not parts:
                raise GatewayError('provider_text_messages_only')
            if any(not isinstance(part, dict) or part.get('type') != 'text' or not isinstance(part.get('text'), str) for part in parts):
                raise GatewayError('provider_text_messages_only')
            messages.append({'role': roles[item['item_type']], 'content': ''.join(part['text'] for part in parts)})
    else:
        messages = request.get('message_list')
        if not isinstance(messages, list):
            raise GatewayError('provider_text_messages_only')
        if any(not isinstance(item, dict) or item.get('role') not in ('system', 'user', 'assistant') or
               not isinstance(item.get('content'), str) for item in messages):
            raise GatewayError('provider_text_messages_only')
        messages = [{'role': item['role'], 'content': item['content']} for item in messages]
    if not 1 <= len(messages) <= 100:
        raise GatewayError('provider_text_messages_only')
    return messages
