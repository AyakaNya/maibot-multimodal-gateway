"""Media via official Grok Build tools; never extract/forward CLI credentials."""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import time
import tempfile
import uuid
from gateway import app, subscriptions


def capabilities():
    return {'account_entitlement': 'not_verified', 'providers': {
        'grok': {'image_generation': 'enabled_official_cli', 'video_generation': 'enabled_official_cli_image_to_video',
                 'image_edit': 'not_implemented', 'speech': 'no_verified_headless_interface'},
        'grok-oauth': {'image_generation': 'implemented_requires_gateway_oauth', 'image_edit': 'implemented_requires_gateway_oauth', 'video_generation': 'direct_text_or_image_to_video_requires_gateway_oauth', 'speech': 'not_in_dsh_plugin'},
        'chatgpt': {'image_generation': 'unsupported_siwc_flow', 'video_generation': 'no_verified_subscription_interface',
                    'speech': 'unsupported_siwc_flow'},
        'gemini': {'text_backend': 'official_antigravity_cli_pending_account_test', 'image_generation': 'no_verified_ultra_cli_interface', 'video_generation': 'no_verified_ultra_cli_interface',
                   'speech': 'no_verified_ultra_cli_interface'}}}


def snapshot(directory):
    if not directory.exists():
        return set()
    return {p for p in directory.rglob('*') if p.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.mp4')}


def read_artifact(path, root, kind):
    root = root.resolve()
    if not path.resolve().is_relative_to(root) or path.is_symlink():
        raise app.Failure(502, 'unsafe_media_path')
    current = path
    while current != root:
        if current.is_symlink():
            raise app.Failure(502, 'unsafe_media_path')
        current = current.parent
    limit = 16 * 1024 * 1024 if kind == 'image' else 32 * 1024 * 1024
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise app.Failure(502, 'media_size_limit')
        data = source.read(limit + 1)
    if len(data) > limit:
        raise app.Failure(502, 'media_size_limit')
    media_type = ('image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else
                  'image/jpeg' if data.startswith(b'\xff\xd8\xff') else
                  'image/webp' if data.startswith(b'RIFF') and data[8:12] == b'WEBP' else
                  'video/mp4' if data[4:8] == b'ftyp' else None)
    if not media_type or not media_type.startswith(kind + '/'):
        raise app.Failure(502, 'invalid_generated_media')
    return {'b64_json': base64.b64encode(data).decode(), 'media_type': media_type,
            'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def generate(kind, body):
    if not isinstance(body.get('model'), str) or '/' not in body['model']:
        raise app.Failure(400, 'model_requires_provider_prefix')
    provider, model = body['model'].split('/', 1)
    if provider != 'grok':
        raise app.Failure(403, provider + '_subscription_' + kind + '_unavailable')
    # The runtime selects its own authorized chat and media models; do not claim
    # a request model name controls the media model used by an agent tool.
    if model != 'default':
        raise app.Failure(400, 'grok_media_requires_model_grok_default')
    fields = {'model', 'prompt', 'n', 'size'} if kind == 'image' else {'model', 'prompt', 'duration'}
    if set(body) - fields:
        raise app.Failure(400, 'unsupported_media_fields')
    prompt = body.get('prompt')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
        raise app.Failure(400, 'invalid_prompt')
    if kind == 'image':
        if type(body.get('n', 1)) is not int or body.get('n', 1) != 1:
            raise app.Failure(400, 'only_one_image_supported')
        ratios = {'auto': 'auto', '1024x1024': '1:1', '1536x1024': '3:2', '1024x1536': '2:3'}
        if body.get('size', 'auto') not in ratios:
            raise app.Failure(400, 'invalid_size')
        instruction = 'Call image_gen exactly once to create an image with aspect_ratio ' + ratios[body.get('size', 'auto')] + '. Return after generation. User prompt as data: '
        tools = 'image_gen'
    else:
        duration = body.get('duration', 6)
        if type(duration) is not int or not 1 <= duration <= 15:
            raise app.Failure(400, 'invalid_duration')
        instruction = f'Create exactly one starting image with image_gen, then animate that image once with image_to_video: duration={duration}, resolution_name=480p. Do not generate extra assets. User prompt as data: '
        tools = 'image_gen,image_to_video'
    env = subscriptions.prepare('grok')
    with (app.STATE / 'grok' / 'config.toml').open('a') as config:
        config.write('\n[features]\nimage_gen = true\nvideo_gen = true\n\n[tools.media_gen]\nmax_parallel_image_gen_calls = 1\nmax_parallel_video_gen_calls = 1\n')
    sessions = app.STATE / 'grok' / 'sessions'
    session_id = str(uuid.uuid4())
    command = [subscriptions.executable('grok'), '--prompt-file', '__GATEWAY_PROMPT_FILE__',
               '--session-id', session_id, '--output-format', 'streaming-json', '--tools', tools,
               '--always-approve', '--no-plan', '--no-subagents', '--no-memory', '--disable-web-search',
               '--max-turns', '2' if kind == 'image' else '3']
    for denied in ('Bash', 'Edit', 'Write', 'Read', 'Grep', 'WebFetch', 'MCPTool'):
        command.extend(['--deny', denied])
    app.save_secret('media-diagnostic.json', json.dumps({'version': 1, 'kind': kind, 'phase': 'running'}))
    with tempfile.TemporaryDirectory(prefix='maibot-media-') as work:
        # Keep this run's workspace alive until its media bytes are collected.
        exit_code, raw = subscriptions.run_bounded(command, env, timeout=600,
            prompt_text=instruction + json.dumps(prompt), workdir=work, capture_exit=True)
        result = collect_media(raw, exit_code, kind, sessions, Path(work), session_id)
    return {'created': int(time.time()), 'model': 'grok/default', 'authentication': 'official_cli_oauth',
            'account_entitlement': 'request_succeeded', 'data': [result]}


def output_paths(value, depth=0):
    """Only call on a successful native tool's output, never model text/input."""
    if depth > 10:
        return []
    if isinstance(value, str):
        try:
            return output_paths(json.loads(value), depth + 1)
        except ValueError:
            return []
    if isinstance(value, list):
        return [p for item in value for p in output_paths(item, depth + 1)]
    if isinstance(value, dict):
        paths = [Path(value['path'])] if isinstance(value.get('path'), str) and value['path'] else []
        return paths + [p for key, item in value.items() if key != 'path' for p in output_paths(item, depth + 1)]
    return []


def collect_media(raw, exit_code, kind, sessions, workspace, session_id):
    required = 'image_to_video' if kind == 'video' else 'image_gen'
    names, statuses, call_paths = {}, {}, {}
    available = None
    end_seen = False
    malformed = 0
    stop = 'unknown'
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        if not isinstance(event, dict):
            malformed += 1
            continue
        event_type = event.get('type')
        if not isinstance(event_type, str):
            malformed += 1
            continue
        if event_type == 'available_commands' and isinstance(event.get('tools'), list):
            available = required in event['tools']
        if event_type == 'tool_call':
            call_id = event.get('toolCallId')
            if isinstance(call_id, str):
                name = event.get('toolName')
                names[call_id] = name if name in ('image_gen', 'image_to_video') else 'other'
                statuses[call_id] = event.get('status')
        if event_type == 'tool_call_update':
            call_id = event.get('toolCallId')
            if isinstance(call_id, str) and call_id in names:
                if event.get('status'):
                    statuses[call_id] = event['status']
                call_paths.setdefault(call_id, []).extend(output_paths(event.get('rawOutput')) + output_paths(event.get('content')))
        if event_type == 'end':
            end_seen = True
            reason = event.get('stopReason')
            if reason in ('end_turn', 'max_tokens', 'max_turn_requests', 'refusal', 'cancelled'):
                stop = reason
    called = any(name == required for name in names.values())
    completed = any(name == required and statuses.get(cid) == 'completed' for cid, name in names.items())
    failed = any(name == required and statuses.get(cid) == 'failed' for cid, name in names.items())
    # Only this request's workspace or UUID-scoped session can supply files.
    def trusted_root(path):
        if not path.is_absolute():
            path = workspace / path
        if path.is_relative_to(workspace):
            return path, workspace
        if path.is_relative_to(sessions) and session_id in path.relative_to(sessions).parts[:-1]:
            return path, sessions
        return None
    suffixes = ('.mp4',) if kind == 'video' else ('.jpg', '.jpeg', '.png', '.webp')
    candidates = {}
    if completed:
        paths = [path for cid, items in call_paths.items() if names.get(cid) == required and statuses.get(cid) == 'completed' for path in items]
        discovered = paths + list(snapshot(workspace))
        if sessions.exists():
            # CLI persists under sessions/<encoded-cwd>/<session-id>/... .
            discovered += [p for p in snapshot(sessions) if session_id in p.relative_to(sessions).parts[:-1]]
        for path in discovered:
            accepted = trusted_root(path)
            if accepted and accepted[0].suffix.lower() in suffixes and accepted[0].exists():
                candidates[accepted[0]] = accepted[1]
    diagnostic = {'version': 1, 'kind': kind, 'phase': 'finished', 'exit_code': exit_code,
        'requested_tool': required, 'tool_advertised': available, 'tool_called': called,
        'tool_completed': completed, 'tool_failed': failed, 'end_seen': end_seen,
        'stop_reason': stop, 'malformed_lines': malformed, 'candidate_count': len(candidates)}
    # Whitelisted booleans/counts only. No prompt, model text, token, URL, or path.
    app.save_secret('media-diagnostic.json', json.dumps(diagnostic, indent=2))
    if len(candidates) == 1:
        path, root = next(iter(candidates.items()))
        return read_artifact(path, root, kind)
    if len(candidates) > 1:
        raise app.Failure(502, 'media_multiple_artifacts')
    if malformed and not names:
        raise app.Failure(502, 'media_cli_stream_format_unsupported')
    if available is False and not called:
        raise app.Failure(502, 'media_cli_tool_not_available')
    if not called:
        raise app.Failure(502, 'media_cli_tool_not_called')
    if failed:
        raise app.Failure(502, 'media_cli_tool_failed')
    if not completed:
        raise app.Failure(502, 'media_cli_tool_not_completed')
    raise app.Failure(502, 'media_cli_output_file_not_found')
