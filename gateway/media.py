"""Media via official Grok Build tools; never extract/forward CLI credentials."""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import time
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
    before = snapshot(sessions)
    command = [subscriptions.executable('grok'), '--prompt-file', '__GATEWAY_PROMPT_FILE__',
               '--session-id', str(uuid.uuid4()), '--output-format', 'json', '--tools', tools,
               '--always-approve', '--no-plan', '--no-subagents', '--no-memory', '--disable-web-search',
               '--max-turns', '2' if kind == 'image' else '3']
    for denied in ('Bash', 'Edit', 'Write', 'Read', 'Grep', 'WebFetch', 'MCPTool'):
        command.extend(['--deny', denied])
    # Official CLI enforces account/tier/remote policy and manages polling. No
    # host token extraction, HTTP permission bypass, or API-key fallback.
    subscriptions.run_bounded(command, env, timeout=600, prompt_text=instruction + json.dumps(prompt))
    suffixes = ('.mp4',) if kind == 'video' else ('.jpg', '.jpeg', '.png', '.webp')
    created = [path for path in snapshot(sessions) - before if path.suffix.lower() in suffixes]
    if len(created) != 1:
        raise app.Failure(502, 'media_artifact_missing_or_ambiguous_check_cli_entitlement')
    result = read_artifact(created[0], sessions, kind)
    return {'created': int(time.time()), 'model': 'grok/default', 'authentication': 'official_cli_oauth',
            'account_entitlement': 'request_succeeded', 'data': [result]}
