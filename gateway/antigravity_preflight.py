"""Offline, redacted checks for native agy shared extension configuration."""
import json
import os
from pathlib import Path
import stat
from gateway import app

EVENTS = {'SessionStart', 'PreToolUse', 'PostToolUse', 'PreInvocation', 'PostInvocation', 'Stop'}
MAX_BYTES = 1024 * 1024


class ExtensionReviewRequired(app.Failure):
    def __init__(self, checks):
        super().__init__(503, 'antigravity_shared_extensions_require_review')
        self.checks = checks


def read_config(path):
    if path.is_symlink():
        return None, 'symlink'
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, encoding='utf-8') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                return None, 'invalid_or_oversized'
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return None, 'invalid_or_oversized'
        value = json.loads(raw)
        return (value, None) if isinstance(value, dict) else (None, 'invalid')
    except FileNotFoundError:
        return {}, None
    except (OSError, ValueError, RecursionError):
        return None, 'unreadable_or_invalid'


def hooks_check(path):
    value, error = read_config(path)
    result = {'state': error or 'inactive', 'enabled_handler_count': 0,
              'disabled_group_count': 0, 'unknown_entry_count': 0}
    if error:
        return {**result, 'review_required': True}
    def handlers(group, allow_disable=True):
        if not isinstance(group, dict):
            result['unknown_entry_count'] += 1
            return
        if allow_disable and group.get('enabled') is False:
            result['disabled_group_count'] += 1
            return
        for key, entries in group.items():
            if key == '$schema' or (key == 'enabled' and type(entries) is bool):
                continue
            if key in EVENTS and isinstance(entries, list):
                result['enabled_handler_count'] += len(entries)
            else:
                result['unknown_entry_count'] += 1
    # Current schema: named hook groups. Also recognize the legacy event map
    # and its "hooks" wrapper; nonempty unknown shapes remain blocked.
    for name, group in value.items():
        if name == '$schema':
            continue
        if name in EVENTS:
            handlers({name: group}, allow_disable=False)
        else:
            handlers(group)
    blocked = bool(result['enabled_handler_count'] or result['unknown_entry_count'])
    return {**result, 'state': 'review_required' if blocked else 'inactive', 'review_required': blocked}


def mcp_check(path):
    value, error = read_config(path)
    result = {'state': error or 'inactive', 'enabled_server_count': 0,
              'disabled_server_count': 0, 'unknown_entry_count': 0}
    if error:
        return {**result, 'review_required': True}
    result['unknown_entry_count'] = len(set(value) - {'$schema', 'mcpServers'})
    servers = value.get('mcpServers', {})
    if not isinstance(servers, dict):
        result['unknown_entry_count'] += 1
    else:
        for server in servers.values():
            if not isinstance(server, dict):
                result['unknown_entry_count'] += 1
            elif server.get('disabled') is True:
                result['disabled_server_count'] += 1
            else:
                result['enabled_server_count'] += 1
    blocked = bool(result['enabled_server_count'] or result['unknown_entry_count'])
    return {**result, 'state': 'review_required' if blocked else 'inactive', 'review_required': blocked}


def plugins_check(path):
    result = {'state': 'inactive', 'candidate_count': 0, 'ignored_entry_count': 0,
              'unknown_entry_count': 0, 'review_required': False}
    try:
        if path.is_symlink():
            return {**result, 'state': 'symlink', 'review_required': True}
        if not path.exists():
            return result
        # Do not follow plugin directories or read manifests/registry contents.
        # Real installs require review; their enabled state is not inferred.
        with os.scandir(path) as entries:
            for index, entry in enumerate(entries):
                if index >= 512:
                    result['unknown_entry_count'] += 1
                    break
                if entry.is_symlink():
                    result['unknown_entry_count'] += 1
                elif entry.is_file(follow_symlinks=False) and (entry.name in ('.DS_Store', '.gitignore') or
                        entry.name.lower() in ('readme', 'readme.md', 'readme.txt', 'license', 'license.md', 'license.txt')):
                    result['ignored_entry_count'] += 1
                elif entry.is_dir(follow_symlinks=False):
                    with os.scandir(entry.path) as children:
                        empty = next(children, None) is None
                    result['ignored_entry_count' if empty else 'candidate_count'] += 1
                else:
                    result['unknown_entry_count'] += 1
    except OSError:
        return {**result, 'state': 'unreadable', 'review_required': True}
    blocked = bool(result['candidate_count'] or result['unknown_entry_count'])
    return {**result, 'state': 'review_required' if blocked else 'inactive', 'review_required': blocked}


def shared_extensions_report():
    base = Path.home() / '.gemini/config'
    checks = {'global_hooks': hooks_check(base / 'hooks.json'),
              'global_mcp': mcp_check(base / 'mcp_config.json'),
              'global_plugins': plugins_check(base / 'plugins')}
    return {'version': 1, 'source': 'local_config_only', 'generation_attempted': False,
            'review_required': any(item['review_required'] for item in checks.values()), 'checks': checks}
