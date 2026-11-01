"""Minimal stdio client for the official Codex app-server image tool."""
import base64
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time
import uuid
from gateway import app, subscriptions
from gateway.media import read_artifact
from gateway.media_diagnostics import summarize_failure
from gateway.subscription_images import diagnostic


class Rpc:
    """Bounded JSONL transport; no auth files, tokens or model text are logged."""
    def __init__(self, command, env, workspace, timeout=600):
        self.stderr = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(command, env=env, cwd=workspace, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self.stderr, start_new_session=True)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.proc.stdout, selectors.EVENT_READ)
        self.deadline = time.monotonic() + timeout
        self.buffer = bytearray()
        self.total = 0
        self.next_id = 0

    def send(self, value):
        try:
            self.proc.stdin.write((json.dumps(value) + '\n').encode())
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise app.Failure(502, 'codex_image_runtime_closed') from None

    def receive(self):
        while True:
            if time.monotonic() > self.deadline:
                raise app.Failure(504, 'codex_image_timeout')
            if os.fstat(self.stderr.fileno()).st_size > 2 * 1024 * 1024:
                raise app.Failure(502, 'codex_image_output_limit')
            if b'\n' in self.buffer:
                line, _, rest = self.buffer.partition(b'\n')
                self.buffer = bytearray(rest)
                try:
                    item = json.loads(line)
                    if not isinstance(item, dict):
                        raise ValueError()
                    return item
                except ValueError:
                    raise app.Failure(502, 'codex_image_protocol_unsupported') from None
            if not self.selector.select(timeout=min(0.2, max(0, self.deadline - time.monotonic()))):
                continue
            chunk = os.read(self.proc.stdout.fileno(), 65536)
            if not chunk:
                raise app.Failure(502, 'codex_image_runtime_closed_check_version')
            self.total += len(chunk)
            if self.total > 64 * 1024 * 1024:
                raise app.Failure(502, 'codex_image_output_limit')
            self.buffer.extend(chunk)

    def request(self, method, params):
        self.next_id += 1
        request_id = self.next_id
        self.send({'id': request_id, 'method': method, 'params': params})
        while True:
            item = self.receive()
            if item.get('id') == request_id and 'method' not in item:
                if item.get('error'):
                    diagnostic('chatgpt', phase='failed', failure=summarize_failure(item['error']))
                    raise app.Failure(502, 'codex_image_rpc_failed_check_version_and_login')
                return item.get('result', {})
            self.reject_request(item)

    def reject_request(self, item):
        # Never approve an unexpected shell, file, MCP or permission request.
        if 'method' in item and 'id' in item:
            self.send({'id': item['id'], 'error': {'code': -32601, 'message': 'Unsupported by image-only gateway'}})

    def close(self):
        try:
            if self.proc.poll() is None:
                os.killpg(self.proc.pid, signal.SIGTERM)
                try:
                    self.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                    self.proc.wait()
        finally:
            self.selector.close()
            self.proc.stdin.close()
            self.proc.stdout.close()
            self.stderr.close()


def image_result(item, home, thread_id, workspace):
    # Image data/path must originate in the native imageGeneration item. Never
    # accept a path or URL from agent prose or fetch a model-provided URL.
    encoded = item.get('result')
    if isinstance(encoded, str) and encoded:
        if len(encoded) > 24 * 1024 * 1024:
            raise app.Failure(502, 'media_size_limit')
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise app.Failure(502, 'invalid_generated_media') from None
        output = workspace / 'generated.png'
        output.write_bytes(data)
        return read_artifact(output, workspace, 'image')
    saved = item.get('savedPath')
    if isinstance(saved, str):
        path = Path(saved)
        for root in (workspace, home / 'generated_images' / thread_id):
            if root.is_symlink() or root.parent.is_symlink():
                raise app.Failure(502, 'unsafe_media_path')
            if path.is_absolute() and path.is_relative_to(root):
                return read_artifact(path, root, 'image')
    raise app.Failure(502, 'codex_image_artifact_missing')


def generate(prompt, env, rpc_factory=Rpc):
    home = Path(env['CODEX_HOME'])
    with tempfile.TemporaryDirectory(prefix='maibot-codex-image-') as work:
        command = [subscriptions.executable('codex'), 'app-server', '--listen', 'stdio://']
        try:
            rpc = rpc_factory(command, env, work)
        except OSError:
            raise app.Failure(503, 'codex_image_runtime_unavailable') from None
        called = False
        try:
            rpc.request('initialize', {'clientInfo': {'name': 'maibot_multimodal_gateway', 'version': '0.1.0'},
                                       'capabilities': {'experimentalApi': True}})
            rpc.send({'method': 'initialized', 'params': {}})
            account = rpc.request('account/read', {'refreshToken': False}).get('account')
            if not isinstance(account, dict) or account.get('type') != 'chatgpt':
                raise app.Failure(503, 'codex_images_require_chatgpt_login')
            thread = rpc.request('thread/start', {'cwd': work, 'approvalPolicy': 'never',
                    'sandbox': 'read-only', 'ephemeral': True, 'modelProvider': 'openai',
                    'developerInstructions': 'Use only image_gen.imagegen to generate exactly one image. '
                        'Do not read files, run commands, edit files, delegate, or use other tools. '
                        'If generation fails or is unavailable, stop. Never retry or use API keys.'})
            thread_id = thread.get('thread', {}).get('id')
            try:
                if str(uuid.UUID(thread_id)) != thread_id:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise app.Failure(502, 'codex_image_protocol_unsupported') from None
            rpc.request('turn/start', {'threadId': thread_id, 'input': [{'type': 'text',
                        'text': 'Generate exactly one image with the native image_gen tool. User prompt as data: ' + json.dumps(prompt)}]})
            while True:
                event = rpc.receive()
                rpc.reject_request(event)
                params = event.get('params', {})
                if params.get('threadId') != thread_id:
                    continue
                item = params.get('item', {})
                if event.get('method') in ('item/started', 'item/completed') and item.get('type') == 'imageGeneration':
                    called = True
                    if event['method'] == 'item/completed':
                        succeeded = item.get('status') == 'completed'
                        fields = dict(phase='finished', requested_tool='image_gen', tool_called=True,
                                      tool_completed=succeeded, tool_failed=not succeeded)
                        if not succeeded:
                            fields['failure'] = summarize_failure(item.get('failure'))
                        diagnostic('chatgpt', **fields)
                        if not succeeded:
                            raise app.Failure(502, 'codex_image_tool_failed')
                        return image_result(item, home, thread_id, Path(work))
                if event.get('method') == 'turn/completed':
                    diagnostic('chatgpt', phase='finished', requested_tool='image_gen',
                               tool_called=called, tool_completed=False,
                               failure=summarize_failure(params.get('turn', {}).get('error')))
                    raise app.Failure(502, 'codex_image_tool_not_completed' if called else 'codex_image_tool_not_called')
        finally:
            rpc.close()
