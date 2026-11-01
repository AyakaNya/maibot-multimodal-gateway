"""Whitelisted media error summaries. Never return raw provider messages."""
import json
import re

CODES = {'http_failure', 'side_call_bearer', 'invalid_arguments', 'permission_denied',
         'insufficient_quota', 'rate_limit_exceeded', 'model_not_found', 'invalid_api_key',
         'content_policy_violation', 'unauthorized', 'forbidden'}


def summarize_failure(value):
    codes, statuses, text = set(), set(), []
    def visit(item, depth=0):
        if depth > 10:
            return
        if isinstance(item, str):
            text.append(item[:16000])
            try:
                parsed = json.loads(item)
            except ValueError:
                return
            if not isinstance(parsed, str):
                visit(parsed, depth+1)
        elif isinstance(item, dict):
            for key, child in list(item.items())[:128]:
                if key in ('code', 'error_code', 'kind', 'type') and isinstance(child, str) and child.lower() in CODES:
                    codes.add(child.lower())
                if key in ('status', 'statusCode', 'status_code', 'http_status') and type(child) is int and 400 <= child <= 599:
                    statuses.add(child)
                if key not in ('rawInput', 'raw_input'):
                    visit(child, depth+1)
        elif isinstance(item, list):
            for child in item[:128]:
                visit(child, depth+1)
    visit(value)
    combined = '\n'.join(text).lower()
    # Match explicit HTTP markers, never arbitrary numbers/IDs in free text.
    for match in re.finditer(r'\b(?:http(?:/\d(?:\.\d)?)?\s+|http[_ -]?status\s*[:=]?\s*|status(?: code)?\s*[:=]\s*)([45]\d\d)\b', combined):
        statuses.add(int(match.group(1)))
    category = 'unknown_tool_error'
    if "login is not an xai credential" in combined:
        category = 'non_xai_login'
    elif 'no xai credential available' in combined:
        category = 'missing_xai_credential'
    elif 'side_call_bearer' in codes:
        category = 'xai_credential_unavailable'
    elif 401 in statuses:
        category = 'api_authentication_failed'
    elif 403 in statuses:
        category = 'api_forbidden'
    elif 429 in statuses:
        category = 'api_rate_limited'
    elif statuses and max(statuses) >= 500:
        category = 'api_server_error'
    elif statuses:
        category = 'api_request_rejected'
    elif any(marker in combined for marker in ('permission denied', 'permission rule', 'denied by', 'not allowed by')):
        category = 'local_permission_denied'
    elif 'invalid_arguments' in codes or any(marker in combined for marker in ('invalid argument', 'invalid aspect', 'invalid prompt', 'invalid parameter')):
        category = 'invalid_tool_arguments'
    elif any(marker in combined for marker in ('timed out', 'timeout', 'connection refused', 'dns error', 'request failed', 'tls error')):
        category = 'transport_failure'
    elif any(marker in combined for marker in ('no space left', 'read-only file system', 'failed to save', 'failed to write')):
        category = 'local_storage_failure'
    return {'category': category, 'http_statuses': sorted(statuses), 'error_codes': sorted(codes)}


def nested_tool_events(value, depth=0):
    """Normalize native ACP updates nested inside persisted JSONL envelopes."""
    if depth > 12:
        return
    if isinstance(value, dict):
        event_type = value.get('type') or value.get('sessionUpdate')
        if event_type in ('tool_call', 'tool_call_update'):
            yield {**value, 'type': event_type}
            return
        for key, child in value.items():
            if key not in ('rawInput', 'raw_input'):
                yield from nested_tool_events(child, depth+1)
    elif isinstance(value, list):
        for child in value[:128]:
            yield from nested_tool_events(child, depth+1)


def cached_image_failure(root):
    """Read only bounded updates.jsonl files; never credentials or auth files."""
    if not root.exists():
        return {'source': 'cached_session_updates', 'found': False, 'logs_scanned': 0}
    files = [path for path in root.rglob('updates.jsonl') if not path.is_symlink() and path.resolve().is_relative_to(root.resolve())]
    files.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    scanned = 0
    for path in files[:12]:
        # Skip huge logs rather than dumping or loading an unbounded transcript.
        if path.stat().st_size > 16 * 1024 * 1024:
            continue
        scanned += 1
        names, values, failed = {}, {}, set()
        with path.open(encoding='utf-8', errors='replace') as source:
            for line in source:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                for event in nested_tool_events(item):
                    cid = event.get('toolCallId')
                    if not isinstance(cid, str):
                        continue
                    if event['type'] == 'tool_call':
                        name = event.get('toolName') or event.get('name')
                        title = event.get('title')
                        normalized = title.lower() if isinstance(title, str) else ''
                        if name == 'image_gen' or any(normalized.startswith(prefix) for prefix in ('image_gen', 'image generation', 'generate image', 'image gen')):
                            names[cid] = 'image_gen'
                    if event['type'] == 'tool_call_update' and names.get(cid) == 'image_gen':
                        values.setdefault(cid, []).append({'rawOutput':event.get('rawOutput'), 'content':event.get('content')})
                        if event.get('status') == 'failed':
                            failed.add(cid)
        for cid in reversed(list(values)):
            if cid in failed:
                return {'source':'cached_session_updates','found':True,'logs_scanned':scanned,
                        'requested_tool':'image_gen', 'failure':summarize_failure(values[cid])}
    return {'source':'cached_session_updates','found':False,'logs_scanned':scanned}
