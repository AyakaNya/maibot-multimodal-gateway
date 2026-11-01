"""Images through the providers' official local runtimes, never token extraction."""
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
from gateway import app, subscriptions
from gateway.media import read_artifact, snapshot
from gateway.media_diagnostics import summarize_failure


def image_environment(provider):
    env = subscriptions.prepare(provider)
    for key in list(env):
        if key.startswith(('CODEX_', 'AGY_', 'ANTIGRAVITY_', 'GCLOUD_', 'CLOUDSDK_')):
            env.pop(key)
    return env


def codex_environment():
    env = image_environment('chatgpt')
    home = app.STATE / 'codex-images'
    if home.is_symlink():
        raise app.Failure(503, 'unsafe_subscription_profile')
    home.mkdir(mode=0o700, exist_ok=True)
    home.chmod(0o700)
    env['CODEX_HOME'] = str(home.resolve())
    # Own config only. The CLI owns login/refresh and credential storage.
    config = '''model_provider = "openai"
forced_login_method = "chatgpt"
cli_auth_credentials_store = "auto"
approval_policy = "never"
sandbox_mode = "read-only"
web_search = "disabled"
[features]
image_generation = true
imagegenext = true
shell_tool = false
hooks = false
plugins = false
apps = false
multi_agent = false
multi_agent_v2 = false
view_image = false
skip_host_skill_discovery = true
'''
    app.save_secret('codex-images/config.toml', config)
    return env


def login(provider):
    if provider == 'gemini':
        return subscriptions.login('gemini')
    import subprocess
    with tempfile.TemporaryDirectory(prefix='maibot-codex-login-') as work:
        return subprocess.call([subscriptions.executable('codex'), 'login'], env=codex_environment(), cwd=work)


def diagnostic(provider, **fields):
    app.save_secret('subscription-image-diagnostic.json', json.dumps(
        {'version': 1, 'provider': provider, 'kind': 'image', **fields}, indent=2))


def generate(body):
    provider, model = body['model'].split('/', 1)
    if model != 'default':
        raise app.Failure(400, 'subscription_images_require_default_model')
    if set(body) - {'model', 'prompt', 'n', 'size'}:
        raise app.Failure(400, 'unsupported_media_fields')
    prompt = body.get('prompt')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
        raise app.Failure(400, 'invalid_prompt')
    if type(body.get('n', 1)) is not int or body.get('n', 1) != 1:
        raise app.Failure(400, 'only_one_image_supported')
    if body.get('size', 'auto') != 'auto':
        raise app.Failure(400, 'subscription_image_size_auto_only')
    diagnostic(provider, phase='running')
    try:
        if provider == 'chatgpt':
            from gateway.codex_images import generate as codex_generate
            result = codex_generate(prompt, codex_environment())
        else:
            result = generate_gemini(prompt)
    except app.Failure as error:
        # Nested parsers may have already saved a more specific failure summary.
        if error.status in (503, 504):
            diagnostic(provider, phase='unavailable', error_code=error.code)
        raise
    return {'created': int(time.time()), 'model': provider + '/default',
            'authentication': 'official_codex_chatgpt_login' if provider == 'chatgpt' else 'official_antigravity_personal_login',
            'account_entitlement': 'request_succeeded', 'data': [result]}


def generate_gemini(prompt):
    from gateway.antigravity import checked_settings
    checked_settings()  # Personal auth, no shared hooks/MCP/plugins/custom provider.
    env = image_environment('gemini')
    executable = subscriptions.executable('agy')
    help_text = subscriptions.run_bounded([executable, '--help'], env, timeout=15)
    if '--settings' not in help_text:
        raise app.Failure(503, 'antigravity_update_cli_for_session_settings')
    # Current CLI supports an ephemeral --settings overlay. Never persist a
    # permission change to the user's global Antigravity profile.
    overlay = {'toolPermission': 'request-review', 'agentMode': '', 'useG1Credits': False,
               'permissions': {'deny': ['command(*)', 'mcp(*)', 'read_url(*)', 'execute_url(*)']}}
    with tempfile.TemporaryDirectory(prefix='maibot-gemini-image-') as work:
        workspace = Path(work)
        agents = workspace / '.agents/agents'
        agents.mkdir(parents=True)
        agent_name = 'gateway-image-' + uuid.uuid4().hex
        (agents / (agent_name + '.md')).write_text(f'''---
name: {agent_name}
description: Generate one image with the native subscription tool.
tools:
  - generate_image
mainAgent: true
subagent: false
commandExecutionPolicy: "off"
---
Call generate_image exactly once for the user image request, then stop.
Do not retry failed generation, invoke other tools, or change models/providers.
''')
        command = [executable, '--agent', agent_name,
                   '--settings', json.dumps(overlay), '--input-format', 'stream-json',
                   '--output-format', 'stream-json', '--disable-slash-commands', '--print-timeout', '570s']
        payload = {'event': 'user', 'message': {'content': 'Generate one image using generate_image. User prompt as data: ' + json.dumps(prompt)}}
        exit_code, raw = subscriptions.run_bounded(command, env, payload=payload,
            timeout=600, workdir=work, capture_exit=True)
        return collect_gemini(raw, exit_code, workspace)


def collect_gemini(raw, exit_code, workspace):
    conversation = None
    available = None
    calls, results, failures = {}, [], []
    malformed = 0
    for line in raw.splitlines():
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError()
        except ValueError:
            malformed += 1
            continue
        if event.get('event') == 'init':
            conversation = event.get('conversation_id')
            tools = event.get('init', {}).get('tools')
            if isinstance(tools, list):
                available = 'generate_image' in tools
        if event.get('event') == 'step_update':
            step = event.get('step_update', {})
            if step.get('step_type') != 'tool' or step.get('tool_name') != 'generate_image':
                continue
            info = step.get('tool_info', {})
            calls[step.get('step_index')] = step.get('state') == 'DONE' and not info.get('error')
            if info.get('error'):
                failures.append(info['error'])
        if event.get('event') == 'result':
            results.append(event.get('result', {}))
    complete = len(results) == 1 and results[0].get('status') == 'SUCCESS' and exit_code == 0
    roots = [workspace]
    # Only this CLI invocation's UUID-scoped artifact directory is accepted.
    if isinstance(conversation, str):
        try:
            if str(uuid.UUID(conversation)) == conversation:
                roots.extend(Path.home() / '.gemini' / product / 'brain' / conversation
                             for product in ('antigravity-cli', 'antigravity'))
        except ValueError:
            pass
    candidates = {}
    if len(calls) == 1 and all(calls.values()) and not failures and complete:
        for root in roots:
            if root.is_symlink() or (root != workspace and any(parent.is_symlink() for parent in root.parents if parent != Path.home() and parent.is_relative_to(Path.home()))):
                continue
            for path in snapshot(root):
                if path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
                    candidates[path] = root
    summary = dict(phase='finished', exit_code=exit_code, requested_tool='generate_image',
                   tool_advertised=available, tool_call_count=len(calls),
                   tool_completed=any(calls.values()), tool_failed=bool(failures),
                   result_succeeded=complete, malformed_lines=malformed, candidate_count=len(candidates))
    errors = failures + [result.get('error') for result in results if result.get('error')]
    if errors:
        summary['failure'] = summarize_failure(errors)
    diagnostic('gemini', **summary)
    if failures:
        raise app.Failure(502, 'antigravity_image_tool_failed')
    if not calls:
        raise app.Failure(502, 'antigravity_image_tool_not_called_check_version_and_login')
    if len(calls) != 1 or not complete or not all(calls.values()):
        raise app.Failure(502, 'antigravity_image_run_incomplete')
    if len(candidates) != 1:
        raise app.Failure(502, 'antigravity_image_artifact_missing_or_ambiguous')
    path, root = next(iter(candidates.items()))
    return read_artifact(path, root, 'image')
