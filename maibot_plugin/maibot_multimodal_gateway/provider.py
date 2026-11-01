"""MaiBot ContextItem to the explicit Grok subscription bridge; no tool execution."""
import base64
import json
import re
from .client import GatewayError, provider_messages, response_text


def encoded_media(value, mime=None, kind='image'):
    if not isinstance(value, str) or len(value) > 6 * 1024 * 1024:
        raise GatewayError('invalid_inline_media')
    try:
        data = base64.b64decode(value, validate=True)
    except ValueError:
        raise GatewayError('invalid_inline_media') from None
    detected = ('image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else
                'image/jpeg' if data.startswith(b'\xff\xd8\xff') else
                'image/webp' if data.startswith(b'RIFF') and data[8:12] == b'WEBP' else
                'image/gif' if data[:6] in (b'GIF87a', b'GIF89a') else
                'audio/wav' if data.startswith(b'RIFF') and data[8:12] == b'WAVE' else
                'audio/mpeg' if data.startswith(b'ID3') or len(data) > 1 and data[0] == 255 and data[1] & 224 == 224 else
                'audio/mp4' if data[4:8] == b'ftyp' else
                'audio/ogg' if data.startswith(b'OggS') else
                'audio/flac' if data.startswith(b'fLaC') else '')
    if not detected.startswith(kind + '/') or mime is not None and detected != mime or not 0 < len(data) <= 4 * 1024 * 1024:
        raise GatewayError('inline_media_type_or_size_mismatch')
    return detected, 'data:' + detected + ';base64,' + value


def validate_definitions(definitions):
    if not isinstance(definitions, list) or len(definitions) > 64:
        raise GatewayError('invalid_tool_definitions')
    if not definitions:
        return
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        raise GatewayError('provider_tool_schema_validator_missing') from None
    names = set()
    try:
        for item in definitions:
            fn = item['function']
            if item['type'] != 'function' or not isinstance(fn['name'], str) or fn['name'] in names:
                raise ValueError()
            names.add(fn['name'])
            schema = fn['parameters']
            if not isinstance(schema, dict) or schema.get('type') != 'object': raise ValueError()
            pending = [(schema, 0)]
            count = 0
            while pending:
                value, depth = pending.pop(); count += 1
                if depth > 64 or count > 8192: raise ValueError()
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key in ('$ref', '$dynamicRef', '$recursiveRef') and (not isinstance(child, str) or not child.startswith('#')):
                            raise ValueError()  # Never resolve a remote schema URL.
                        pending.append((child, depth + 1))
                elif isinstance(value, list):
                    pending.extend((child, depth + 1) for child in value)
            Draft202012Validator.check_schema(schema)
    except Exception:
        raise GatewayError('invalid_or_remote_tool_schema') from None


def request_body(request, model, features):
    definitions = request.get('tool_options') or []
    if definitions and not features.provider_tool_calls_enabled:
        raise GatewayError('provider_tool_calls_not_enabled')
    validate_definitions(definitions)
    if request.get('response_format') not in (None, {}, {'type': 'text'}):
        raise GatewayError('provider_structured_output_not_supported')
    if request.get('tool_choice') not in (None, '', 'auto', 'none'):
        raise GatewayError('grok_only_auto_or_none_tool_choice_supported')
    if 'context_items' not in request:
        # Legacy images/tools have no stable ContextItem contract. Text remains supported.
        messages = provider_messages({**request, 'tool_options': [], 'tool_choice': None})
    else:
        if request.get('item_schema_version') != 1 or not isinstance(request['context_items'], list):
            raise GatewayError('unsupported_context_schema')
        messages = []
        roles = {'SystemMessageItem': 'system', 'UserMessageItem': 'user', 'AssistantMessageItem': 'assistant'}
        for item in request['context_items']:
            if not isinstance(item, dict):
                raise GatewayError('invalid_context_item')
            kind = item.get('item_type')
            if kind in roles:
                parts = item.get('parts')
                if not isinstance(parts, list) or not parts:
                    raise GatewayError('invalid_context_parts')
                content = []
                for part in parts:
                    if not isinstance(part, dict): raise GatewayError('invalid_context_part')
                    if part.get('type') == 'text' and isinstance(part.get('text'), str):
                        content.append({'type': 'text', 'text': part['text']})
                    elif part.get('type') == 'image' and kind == 'UserMessageItem':
                        if not features.provider_vision_enabled: raise GatewayError('provider_vision_not_enabled')
                        fmt = str(part.get('image_format', '')).lower()
                        mime = 'image/jpeg' if fmt in ('jpg', 'jpeg') else 'image/' + fmt
                        _, url = encoded_media(part.get('image_base64'), mime)
                        content.append({'type': 'image_url', 'image_url': {'url': url}})
                    else:
                        raise GatewayError('unsupported_context_part')
                if all(part['type'] == 'text' for part in content):
                    content = ''.join(part['text'] for part in content)
                messages.append({'role': roles[kind], 'content': content})
            elif kind == 'FunctionCallItem':
                if not features.provider_tool_calls_enabled: raise GatewayError('provider_tool_calls_not_enabled')
                call = item.get('tool_call')
                if not isinstance(call, dict) or not isinstance(call.get('args'), dict):
                    raise GatewayError('invalid_context_tool_call')
                fn = {'id': call.get('call_id'), 'type': 'function', 'function': {
                    'name': call.get('func_name'), 'arguments': json.dumps(call['args'], ensure_ascii=False)}}
                if messages and messages[-1]['role'] == 'assistant' and isinstance(messages[-1].get('content'), (str, type(None))):
                    messages[-1].setdefault('tool_calls', []).append(fn)
                else:
                    messages.append({'role': 'assistant', 'content': None, 'tool_calls': [fn]})
            elif kind == 'FunctionCallOutputItem':
                if not features.provider_tool_calls_enabled: raise GatewayError('provider_tool_calls_not_enabled')
                if not isinstance(item.get('output'), str): raise GatewayError('tool_result_text_required')
                messages.append({'role': 'tool', 'tool_call_id': item.get('call_id'), 'content': item['output']})
            else:
                raise GatewayError('unsupported_context_item')
    if not 1 <= len(messages) <= 100:
        raise GatewayError('invalid_provider_messages')
    return {'model': model, 'messages': messages, 'stream': False, 'tools': definitions,
            'tool_choice': request.get('tool_choice') or 'auto'}


def output(result, definitions, modern=True):
    try:
        message = result['choices'][0]['message']
        calls = message.get('tool_calls')
        if not calls:
            text = response_text(result)
            return ({'item_schema_version': 1, 'output_items': [
                {'item_type': 'AssistantMessageItem', 'parts': [{'type': 'text', 'text': text}], 'phase': 'final'}]}
                    if modern else {'content': text})
        # The bridge deliberately serializes tool dispatches one at a time.
        if not modern or not isinstance(calls, list) or len(calls) != 1:
            raise ValueError()
        call = calls[0]; fn = call['function']
        if call.get('type') != 'function' or fn['name'] not in {item['function']['name'] for item in definitions}:
            raise ValueError()
        if not isinstance(call['id'], str) or not re.fullmatch(r'gw_[a-f0-9]{48}', call['id']):
            raise ValueError()
        args = json.loads(fn['arguments'])
        if not isinstance(args, dict): raise ValueError()
        validate_definitions(definitions)
        from jsonschema import Draft202012Validator
        schema = next(item['function']['parameters'] for item in definitions if item['function']['name'] == fn['name'])
        try:
            valid = Draft202012Validator(schema).is_valid(args)
        except Exception:
            raise GatewayError('invalid_or_unresolved_tool_schema') from None
        if not valid:
            raise ValueError()
        items = []
        text = message.get('content')
        if text:
            if not isinstance(text, str) or len(text) > 64000: raise ValueError()
            items.append({'item_type': 'AssistantMessageItem', 'parts': [{'type': 'text', 'text': text}], 'phase': 'commentary'})
        items.append({'item_type': 'FunctionCallItem', 'tool_call': {
            'call_id': call['id'], 'func_name': fn['name'], 'args': args, 'extra_content': None}})
        return {'item_schema_version': 1, 'output_items': items}
    except (KeyError, IndexError, ValueError, TypeError):
        raise GatewayError('invalid_gateway_tool_response') from None
