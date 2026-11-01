import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from gateway import app

class Transport:
    def __init__(self):
        self.requests = []
    def open(self, request, timeout):
        self.requests.append(request)
        if request.full_url.endswith('/images/generations'):
            return io.BytesIO(json.dumps({'data': [{'b64_json': 'iVBORw0KGgo='}]}).encode())
        return io.BytesIO(json.dumps({'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'hello'}]}]}).encode())

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(app, 'STATE', Path(self.temp.name) / 'secrets')
        self.patch.start()
        app.save_secret('openai.key', 'test-upstream')
        app.save_secret('xai.key', 'test-upstream')
        self.transport = Transport()
        self.gateway = app.Gateway('local-key', self.transport)
    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()
    def call_http(self, body, key='local-key', path='/v1/chat/completions'):
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(), {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)
    def test_http_text_image_and_auth(self):
        server = app.server(self.gateway, 0)
        self.base = 'http://127.0.0.1:' + str(server.server_port)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            text = {'model': 'openai/gpt-4.1-mini', 'messages': [{'role': 'user', 'content': 'hi'}]}
            status, result = self.call_http(text)
            self.assertEqual(status, 200)
            self.assertEqual(result['choices'][0]['message']['content'], 'hello')
            self.assertEqual(self.call_http(text, 'wrong')[0], 401)
            status, result = self.call_http({'model': 'xai/grok-imagine-image', 'prompt': 'apple'}, path='/v1/images/generations')
            self.assertEqual(status, 200)
            self.assertIn('b64_json', result['data'][0])
            self.assertEqual(self.transport.requests[-1].full_url, 'https://api.x.ai/v1/images/generations')
            self.assertEqual(self.transport.requests[-1].get_header('Authorization'), 'Bearer test-upstream')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
    def test_busy_releases_and_no_fallback(self):
        self.gateway.slots.acquire()
        with self.assertRaises(app.Failure) as caught:
            self.gateway.dispatch('/v1/chat/completions', {'model': 'xai/grok-test', 'messages': [{'role': 'user', 'content': 'hi'}]})
        self.assertEqual(caught.exception.status, 429)
        self.gateway.slots.release()
        with self.assertRaises(app.Failure) as caught:
            self.gateway.dispatch('/v1/images/generations', {'model': 'grok-oauth/default', 'prompt': 'a'})
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(len(self.transport.requests), 0)
    def test_secret_permissions(self):
        self.assertEqual((app.STATE / 'openai.key').stat().st_mode & 0o777, 0o600)
        (app.STATE / 'openai.key').chmod(0o644)
        with self.assertRaises(RuntimeError):
            app.read_secret('openai.key')
    def test_upstream_denial(self):
        class Denied:
            def open(self, *args, **kwargs):
                raise urllib.error.HTTPError('https://api.x.ai', 403, 'secret-body', {}, None)
        with self.assertRaises(app.Failure) as caught:
            app.upstream('https://api.x.ai/v1/responses', 'secret', {}, Denied())
        self.assertEqual(caught.exception.code, 'upstream_403')
    def test_oauth_endpoint_validation(self):
        from gateway.oauth import checked
        for url in ['http://auth.x.ai/token', 'https://evil.test/token', 'https://auth.x.ai@evil.test/token']:
            with self.assertRaises(RuntimeError):
                checked(url)

if __name__ == '__main__':
    unittest.main()
