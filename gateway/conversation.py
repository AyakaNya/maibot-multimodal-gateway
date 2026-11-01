"""Bounded chat/tool wire validation shared by local subscription adapters."""
import base64
import json
import re
from gateway import app

NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_.:-]{0,127}')
CALL = re.compile(r'[A-Za-z0-9_-]{1,160}')
MAX_MEDIA = 4 * 1024 * 1024


def fail(code='invalid_conversation'):
    raise app.Failure(400, code)


def media_url(value, kind):
    if not isinstance(value, str) or len(value) > 6 * 1024 * 1024:
        fail('invalid_inline_media')
    match = re.fullmatch(r'data:([a-z0-9/+.-]+);base64,([A-Za-z0-9+/=]+)', value)
    if not match:
        fail('inline_media_required_no_urls_or_paths')
    mime, encoded = match.groups()
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError:
        fail('invalid_inline_media')
    if not data or len(data) > MAX_MEDIA:
        fail('inline_media_size_limit')
    valid = {'image/png': data.startswith(b'\x89PNG\r\n\x1a\n'),
             'image/jpeg': data.startswith(b'\xff\xd8\xff'),
             'image/webp': data.startswith(b'RIFF') and data[8:12] == b'WEBP',
             'image/gif': data[:6] in (b'GIF87a', b'GIF89a'),
             'audio/wav': data.startswith(b'RIFF') and data[8:12] == b'WAVE',
             'audio/mpeg': data.startswith(b'ID3') or len(data) > 1 and data[0] == 255 and data[1] & 224 == 224,
             'audio/mp4': data[4:8] == b'ftyp',
             'audio/ogg': data.startswith(b'OggS'),
             'audio/flac': data.startswith(b'fLaC')}
    if not mime.startswith(kind + '/') or not valid.get(mime):
        fail('inline_media_type_mismatch')
    return value


def tools(value):
    if not isinstance(value, list) or len(value) > 64:
        fail('invalid_tools')
    names = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {'type', 'function'} or item['type'] != 'function':
            fail('function_tools_only')
        fn = item['function']
        if not isinstance(fn, dict) or set(fn) - {'name', 'description', 'parameters', 'strict'}:
            fail('invalid_tool_definition')
        name = fn.get('name')
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in names:
            fail('invalid_or_duplicate_tool_name')
        if not isinstance(fn.get('description', ''), str) or len(fn.get('description', '')) > 16000:
            fail('invalid_tool_description')
        schema = fn.get('parameters', {})
        if not isinstance(schema, dict) or schema.get('type') != 'object':
            fail('tool_object_schema_required')
        if len(json.dumps(schema)) > 65536:
            fail('tool_schema_too_large')
        names.add(name)
    return value


def choice(value, definitions):
    if value not in (None, 'auto', 'none'):
        # This bridge does not support forced/required tool selection.
        # Refuse rather than pretending that a prompt enforces this constraint.
        fail('grok_only_auto_or_none_tool_choice_supported')
    return value or 'auto'


def arguments(value):
    if not isinstance(value, str) or len(value) > 65536:
        fail('invalid_tool_arguments')
    try:
        result = json.loads(value)
    except ValueError:
        fail('invalid_tool_arguments')
    if not isinstance(result, dict):
        fail('tool_arguments_must_be_object')
    return result


def messages(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        fail('invalid_messages')
    pending = set()
    ids = set()
    images = audio = 0
    for msg in value:
        if not isinstance(msg, dict) or set(msg) - {'role', 'content', 'tool_calls', 'tool_call_id'}:
            fail()
        role = msg.get('role')
        if role not in ('system', 'user', 'assistant', 'tool'):
            fail()
        content = msg.get('content')
        if role == 'tool':
            if set(msg) != {'role', 'content', 'tool_call_id'} or msg['tool_call_id'] not in pending or not isinstance(content, str):
                fail('unmatched_tool_result')
            pending.remove(msg['tool_call_id'])
        else:
            if pending:
                fail('tool_results_required_before_new_message')
            if 'tool_call_id' in msg:
                fail()
            if isinstance(content, list):
                if role != 'user' or not content or len(content) > 16:
                    fail('user_multimodal_parts_only')
                for part in content:
                    if not isinstance(part, dict): fail()
                    if part.get('type') == 'text' and set(part) == {'type', 'text'} and isinstance(part['text'], str):
                        continue
                    if part.get('type') == 'image_url' and set(part) == {'type', 'image_url'}:
                        image = part['image_url']
                        if not isinstance(image, dict) or set(image) != {'url'}: fail()
                        media_url(image['url'], 'image'); images += 1
                    elif part.get('type') == 'input_audio' and set(part) == {'type', 'audio_url'}:
                        media_url(part['audio_url'], 'audio'); audio += 1
                    else: fail('unsupported_content_part')
            elif not isinstance(content, str) and not (role == 'assistant' and content is None and msg.get('tool_calls')):
                fail()
            calls = msg.get('tool_calls', [])
            if calls:
                if role != 'assistant' or not isinstance(calls, list) or len(calls) > 16:
                    fail('invalid_tool_calls')
                for call in calls:
                    if not isinstance(call, dict) or set(call) != {'id', 'type', 'function'} or call['type'] != 'function': fail()
                    call_id = call['id']; fn = call['function']
                    if not isinstance(call_id, str) or not CALL.fullmatch(call_id) or call_id in ids: fail('duplicate_or_invalid_tool_call_id')
                    if not isinstance(fn, dict) or set(fn) != {'name', 'arguments'} or not isinstance(fn['name'], str) or not NAME.fullmatch(fn['name']): fail()
                    arguments(fn['arguments']); pending.add(call_id); ids.add(call_id)
    if pending:
        fail('tool_results_missing')
    if images > 4 or audio > 1:
        fail('too_many_inline_media')
    return value


def has_media(items):
    return any(isinstance(item.get('content'), list) for item in items)
