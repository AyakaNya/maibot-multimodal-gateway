"""Single-user, loopback-only gateway. Python 3.12+, no dependencies."""
import argparse
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Keep one Failure class/state when started with python -m gateway.app.
if __name__ == '__main__':
    sys.modules['gateway.app'] = sys.modules[__name__]

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.state'
MAX_BODY = 1024 * 1024
MAX_RESPONSE = 24 * 1024 * 1024

class Failure(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def secure_dir():
    if STATE.is_symlink():
        raise RuntimeError('state must not be a symlink')
    STATE.mkdir(mode=0o700, exist_ok=True)
    STATE.chmod(0o700)


def save_secret(name, value):
    secure_dir()
    target = STATE / name
    temp = STATE / ('.tmp-' + secrets.token_hex(12))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write(value)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, target)


def read_secret(name):
    path = STATE / name
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(fd) as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise RuntimeError('unsafe secret permissions')
        return source.read().strip()


def upstream(url, key, body, transport=None):
    request = urllib.request.Request(url, json.dumps(body).encode(),
        {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        # Do not follow redirects: a credential must never leave the fixed origin.
        opener = transport or urllib.request.build_opener(NoRedirect)
        with opener.open(request, timeout=120) as response:
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                raise Failure(502, 'upstream_response_too_large')
            return json.loads(data)
    except urllib.error.HTTPError as error:
        status = error.code if error.code in (401, 403, 429) else 502
        raise Failure(status, 'upstream_' + str(error.code)) from None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        raise Failure(502, 'upstream_unavailable') from None

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Gateway:
    def __init__(self, key, transport=None, limit=1):
        self.key, self.transport = key, transport
        self.slots = threading.BoundedSemaphore(limit)

    def dispatch(self, path, body):
        if path in ('/v1/images/generations', '/v1/images/edits', '/v1/videos/generations') and isinstance(body.get('model'), str) and body['model'].startswith('grok-oauth/'):
            from gateway.direct_media import generate
            if not self.slots.acquire(blocking=False):
                raise Failure(429, 'gateway_busy')
            try:
                kind = 'video' if '/videos/' in path else 'edit' if path.endswith('/edits') else 'image'
                return generate(kind, body, transport=self.transport)
            finally:
                self.slots.release()
        if path in ('/v1/videos/generations', '/v1/audio/speech', '/v1/audio/transcriptions') or (path == '/v1/images/generations' and isinstance(body.get('model'), str) and body['model'].startswith('grok/')):
            from gateway.media import generate
            if path.startswith('/v1/audio/'):
                raise Failure(501, 'subscription_audio_interface_unavailable')
            if not self.slots.acquire(blocking=False):
                raise Failure(429, 'gateway_busy')
            try:
                return generate('video' if '/videos/' in path else 'image', body)
            finally:
                self.slots.release()
        if path not in ('/v1/chat/completions', '/v1/images/generations'):
            raise Failure(404, 'route_not_implemented')
        model = body.get('model')
        if not isinstance(model, str) or '/' not in model:
            raise Failure(400, 'model_requires_provider_prefix')
        provider, model = model.split('/', 1)
        if provider not in ('openai', 'xai', 'grok-oauth', 'chatgpt', 'grok', 'gemini') or not model:
            raise Failure(400, 'unsupported_provider')
        image = path.endswith('generations')
        allowed = {'model', 'prompt', 'n', 'size'} if image else {'model', 'messages', 'stream'}
        if set(body) - allowed:
            raise Failure(400, 'unsupported_fields')
        if image:
            if not isinstance(body.get('prompt'), str) or not 1 <= len(body['prompt']) <= 16000:
                raise Failure(400, 'invalid_prompt')
            if type(body.get('n', 1)) is not int or body.get('n', 1) != 1:
                raise Failure(400, 'only_one_image_supported')
            if body.get('size', '1024x1024') not in ('1024x1024', '1536x1024', '1024x1536', 'auto'):
                raise Failure(400, 'invalid_size')
            if provider in ('grok-oauth', 'chatgpt', 'grok', 'gemini'):
                raise Failure(403, 'subscription_image_entitlement_unverified')
        else:
            messages = body.get('messages')
            if not isinstance(messages, list) or not 1 <= len(messages) <= 100:
                raise Failure(400, 'invalid_messages')
            for msg in messages:
                if not isinstance(msg, dict) or set(msg) != {'role', 'content'} or msg['role'] not in ('system', 'user', 'assistant') or not isinstance(msg['content'], str):
                    raise Failure(400, 'text_messages_only')
            if body.get('stream', False) is not False:
                raise Failure(400, 'streaming_not_implemented')
        if not self.slots.acquire(blocking=False):
            raise Failure(429, 'gateway_busy')
        try:
            if provider in ('chatgpt', 'grok', 'gemini'):
                from gateway.subscriptions import generate
                text = generate(provider, model, messages)
                return {'id': 'subscription-' + secrets.token_hex(8), 'object': 'chat.completion', 'created': int(time.time()), 'model': body['model'], 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': text}, 'finish_reason': 'stop'}]}
            if provider == 'grok-oauth':
                from gateway.oauth import access_token
                credential = access_token()
            else:
                credential = read_secret(provider + '.key')
            if not credential:
                raise Failure(503, 'provider_not_configured')
            payload = {**body, 'model': model}
            if image:
                if provider == 'xai':
                    size = payload.pop('size', None)
                    if size and size != 'auto':
                        payload['aspect_ratio'] = {'1024x1024': '1:1', '1536x1024': '3:2', '1024x1536': '2:3'}[size]
                    payload['response_format'] = 'b64_json'
                url = ('https://api.openai.com' if provider == 'openai' else 'https://api.x.ai') + path
                return upstream(url, credential, payload, self.transport)
            # Responses format avoids xAI models restricted to /responses.
            url = ('https://api.openai.com' if provider == 'openai' else 'https://api.x.ai') + '/v1/responses'
            result = upstream(url, credential, {'model': model, 'input': messages, 'stream': False}, self.transport)
            text = ''.join(part.get('text', '') for item in result.get('output', []) if item.get('type') == 'message' for part in item.get('content', []) if part.get('type') == 'output_text')
            if not text:
                raise Failure(502, 'upstream_missing_text')
            return {'id': result.get('id', 'gateway'), 'object': 'chat.completion', 'created': int(time.time()), 'model': body['model'], 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': text}, 'finish_reason': 'stop'}]}
        finally:
            self.slots.release()


def server(gateway, port=8790):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # never log prompts, bearer tokens, or upstream error bodies

        def reply(self, status, value):
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def handle_request(self):
            self.connection.settimeout(10)
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + gateway.key):
                raise Failure(401, 'invalid_gateway_key')
            if self.command == 'GET':
                if self.path == '/v1/capabilities':
                    from gateway.media import capabilities
                    return self.reply(200, capabilities())
                if self.path == '/health':
                    return self.reply(200, {'status': 'ok'})
                raise Failure(404, 'route_not_implemented')
            if self.headers.get('Transfer-Encoding'):
                raise Failure(400, 'chunked_body_not_supported')
            if self.headers.get_content_type() != 'application/json':
                raise Failure(415, 'json_required')
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                raise Failure(400, 'invalid_length')
            if not 0 < length <= MAX_BODY:
                raise Failure(413, 'body_size_limit')
            try:
                body = json.loads(self.rfile.read(length))
            except (ValueError, TimeoutError):
                raise Failure(400, 'invalid_json')
            if not isinstance(body, dict):
                raise Failure(400, 'json_object_required')
            self.reply(200, gateway.dispatch(self.path, body))

        def run_request(self):
            self.close_connection = True
            try:
                self.handle_request()
            except Failure as error:
                self.reply(error.status, {'error': {'code': error.code, 'message': error.code, 'type': 'gateway_error'}})
            except Exception:
                self.reply(500, {'error': {'code': 'internal_error'}})
        do_GET = run_request
        do_POST = run_request
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init', 'set-key', 'serve', 'login-grok', 'login', 'models'])
    parser.add_argument('--provider', choices=['openai', 'xai', 'chatgpt', 'grok', 'gemini'])
    parser.add_argument('--port', type=int, default=8790)
    args = parser.parse_args()
    if args.command == 'init':
        if not read_secret('gateway.key'):
            save_secret('gateway.key', secrets.token_urlsafe(32))
        print('Gateway key saved in .state/gateway.key (0600); value hidden.')
    elif args.command in ('login', 'models'):
        from gateway.subscriptions import login, prepare, chatgpt_command, run_bounded
        if args.provider not in ('chatgpt', 'grok', 'gemini'):
            parser.error('--provider chatgpt|grok|gemini required')
        try:
            if args.command == 'login':
                raise SystemExit(login(args.provider))
            if args.provider == 'gemini':
                from gateway.subscriptions import executable
                print(run_bounded([executable('agy'), 'models'], prepare('gemini')))
                return
            if args.provider != 'chatgpt':
                parser.error('Use GROK_HOME=... grok models; see docs/MACOS.md')
            print(run_bounded(chatgpt_command('models'), prepare('chatgpt')))
        except Failure as error:
            parser.exit(1, error.code + '\n')
    elif args.command == 'set-key':
        if args.provider not in ('openai', 'xai'):
            parser.error('--provider openai|xai required')
        key = getpass.getpass('Official API key: ').strip()
        if not key or any(c.isspace() for c in key):
            parser.error('invalid key')
        save_secret(args.provider + '.key', key)
    elif args.command == 'login-grok':
        from gateway.oauth import login
        login()
    else:
        key = read_secret('gateway.key')
        if not key:
            parser.error('run init first')
        print(f'Listening on http://127.0.0.1:{args.port}; concurrency=1')
        server(Gateway(key), args.port).serve_forever()

if __name__ == '__main__':
    main()
