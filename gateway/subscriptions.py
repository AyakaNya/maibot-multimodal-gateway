"""Official local runtimes; credentials remain owned by their SDK/CLI."""
import json
from contextlib import nullcontext
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
from gateway import app

PROVIDERS = ('chatgpt', 'grok', 'gemini')


def prepare(provider):
    app.secure_dir()
    profile = app.STATE / provider
    if profile.is_symlink():
        raise app.Failure(503, 'unsafe_subscription_profile')
    profile.mkdir(mode=0o700, exist_ok=True)
    profile.chmod(0o700)
    env = os.environ.copy()
    # Explicit subscription routes must never fall back to a billed API key.
    for key in list(env):
        if key.startswith(('OPENAI_', 'XAI_', 'GEMINI_', 'GROK_', 'GOOGLE_')):
            env.pop(key)
    env['GROK_HOME'] = str(app.STATE / 'grok')
    env['GEMINI_CLI_HOME'] = str(app.STATE / 'gemini')
    env['GROK_WORKFLOWS'] = '0'
    env['GROK_DISABLE_AUTOUPDATER'] = '1'
    if provider == 'grok':
        config = '[auth]\npreferred_method = "oidc"\ndisable_api_key_auth = true\n'
        for source in ('claude', 'codex', 'cursor'):
            config += f'\n[compat.{source}]\n'
            for feature in ('agents', 'hooks', 'mcps', 'rules', 'skills'):
                if source == 'codex' and feature not in ('hooks', 'skills'):
                    continue
                config += f'{feature} = false\n'
        config += '\n[workflows]\nenabled = false\n'
        (profile / 'config.toml').write_text(config)
        (profile / 'config.toml').chmod(0o600)
    # agy uses its own native keyring/shared settings; old Gemini CLI settings
    # and credentials are preserved and are not read or migrated automatically.
    env.pop('AGY_ADC_AUTH', None)
    if provider == 'gemini':
        env.pop('GEMINI_CLI_HOME', None)
    return env


def executable(name):
    path = shutil.which(name)
    if not path:
        raise app.Failure(503, name + '_not_installed')
    return path


def chatgpt_command(command):
    return [executable('node'), str(app.ROOT / 'integrations/chatgpt/bridge.mjs'), command]


def login(provider):
    env = prepare(provider)
    command = chatgpt_command('login') if provider == 'chatgpt' else [executable('grok'), 'login'] if provider == 'grok' else [executable('agy')]
    print('Complete browser sign-in. Google AI Ultra uses Antigravity (agy). For Google text routes, set Tool Permission to strict in /config, then /quit. Image routes use a per-session permission override. Global settings are shared with your other agy sessions.')
    with tempfile.TemporaryDirectory(prefix='maibot-login-') as work:
        return subprocess.call(command, env=env, cwd=work)


def run_bounded(command, env, payload=None, timeout=150, prompt_text=None, workdir=None, capture_exit=False):
    # Private files cap output without buffering an unbounded CLI stdout in RAM.
    with (tempfile.TemporaryDirectory(prefix='maibot-text-') if workdir is None else nullcontext(workdir)) as work, tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as source:
        if prompt_text is not None:
            prompt_file = Path(work) / 'prompt.txt'
            prompt_file.write_text(prompt_text)
            prompt_file.chmod(0o600)
            command = [str(prompt_file) if arg == '__GATEWAY_PROMPT_FILE__' else arg for arg in command]
        if payload is not None:
            source.write((json.dumps(payload) + '\n').encode())
            source.seek(0)
        try:
            proc = subprocess.Popen(command, stdin=source if payload is not None else subprocess.DEVNULL,
                                    stdout=out, stderr=err, cwd=work, env=env, start_new_session=True)
        except OSError:
            raise app.Failure(503, 'subscription_runtime_unavailable') from None
        try:
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                if time.monotonic() > deadline:
                    raise app.Failure(504, 'subscription_timeout')
                if os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > 2 * 1024 * 1024:
                    raise app.Failure(502, 'subscription_output_limit')
                time.sleep(0.05)
            if proc.returncode and not capture_exit:
                # No raw stderr: it can contain tokens, URLs or private prompts.
                raise app.Failure(502, 'subscription_runtime_failed_check_local_login_and_model')
            if os.fstat(out.fileno()).st_size > 2 * 1024 * 1024:
                raise app.Failure(502, 'subscription_output_limit')
            out.seek(0)
            output = out.read().decode('utf-8')
            return (proc.returncode, output) if capture_exit else output
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


def generate(provider, model, messages):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,199}', model):
        raise app.Failure(400, 'invalid_subscription_model')
    env = prepare(provider)
    if provider == 'gemini':
        from gateway.antigravity import generate as generate_antigravity
        return generate_antigravity(model, messages, env)
    if provider == 'chatgpt':
        payload = {'model': model, 'messages': messages}
        raw = run_bounded(chatgpt_command('text'), env, payload)
    else:
        # Preserve roles as data. This CLI bridge does not provide native chat semantics.
        prompt = 'Reply to the last user message in this JSON conversation. Do not use tools.\n' + json.dumps(messages, ensure_ascii=False)
        if len(prompt.encode()) > 64 * 1024:
            raise app.Failure(413, 'subscription_conversation_too_large')
        if provider == 'grok':
            command = [executable('grok'), '--prompt-file', '__GATEWAY_PROMPT_FILE__', '--model', model, '--output-format', 'json',
                       '--tools', '', '--deny', 'Bash', '--deny', 'Edit', '--deny', 'Write', '--deny', 'Read', '--deny', 'Grep', '--deny', 'WebFetch', '--deny', 'MCPTool', '--no-plan', '--no-subagents', '--no-memory',
                       '--disable-web-search', '--max-turns', '1']
        else:
            raise app.Failure(400, 'unsupported_subscription_provider')
        if model == 'default':
            index = command.index('--model')
            del command[index:index + 2]
        raw = run_bounded(command, env, prompt_text=prompt) if provider == 'grok' else run_bounded(command, env, payload=messages)
    try:
        result = json.loads(raw)
    except ValueError:
        raise app.Failure(502, 'subscription_invalid_json') from None
    if not isinstance(result, dict) or result.get('error') or result.get('is_error'):
        raise app.Failure(502, 'subscription_request_failed')
    text = result.get('text') if provider == 'chatgpt' else result.get('response') if provider == 'gemini' else result.get('text')
    if not isinstance(text, str) or not text.strip():
        raise app.Failure(502, 'subscription_missing_text_check_cli_version')
    return text
