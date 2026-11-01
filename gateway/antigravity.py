"""Official agy CLI bridge for Google AI personal subscriptions.

Uses native sign-in/keyring. Never reads token files or rewrites global settings.
"""
import json
from pathlib import Path
from gateway import app


def checked_settings(*, require_strict=True):
    base = Path.home() / '.gemini'
    settings_path = base / 'antigravity-cli/settings.json'
    try:
        settings = json.loads(settings_path.read_text())
    except FileNotFoundError:
        settings = {}
    except (OSError, ValueError):
        raise app.Failure(503, 'antigravity_invalid_settings_file') from None
    if not isinstance(settings, dict):
        raise app.Failure(503, 'antigravity_invalid_settings_file')
    # Text has no session permission overlay. The image adapter instead checks
    # --settings support and supplies its own constrained per-session policy.
    if require_strict and settings.get('toolPermission') != 'strict':
        raise app.Failure(503, 'antigravity_set_toolPermission_strict_in_config')
    # Native default account authentication is the subscription path. Refuse
    # custom providers / enterprise project routing, rather than silently billing.
    if settings.get('modelProvider') or settings.get('gcp') or settings.get('customModelsConfig'):
        raise app.Failure(503, 'antigravity_requires_personal_account_auth')
    from gateway.antigravity_preflight import ExtensionReviewRequired, shared_extensions_report
    report = shared_extensions_report()
    if report['review_required']:
        raise ExtensionReviewRequired(report['checks'])
    return settings


def generate(model, messages, env):
    from gateway.subscriptions import executable, run_bounded
    checked_settings()
    command = [executable('agy'), '--input-format', 'stream-json', '--output-format', 'stream-json',
               '--disable-slash-commands', '--mode', 'plan', '--print-timeout', '120s']
    if model != 'default':
        command.extend(['--model', model])
    conversation = 'Answer the last user message in this JSON conversation. Do not use tools.\n' + json.dumps(messages, ensure_ascii=False)
    payload = {'event': 'user', 'message': {'content': conversation}}
    raw = run_bounded(command, env, payload=payload)
    try:
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except ValueError:
        raise app.Failure(502, 'antigravity_invalid_stream') from None
    results = [event.get('result') for event in events if isinstance(event, dict) and event.get('event') == 'result']
    if len(results) != 1 or not isinstance(results[0], dict):
        raise app.Failure(502, 'antigravity_missing_result')
    result = results[0]
    if result.get('status') != 'SUCCESS' or result.get('error'):
        raise app.Failure(502, 'antigravity_request_failed_check_local_login')
    if not isinstance(result.get('response'), str) or not result['response'].strip():
        raise app.Failure(502, 'antigravity_missing_text')
    return result['response']
