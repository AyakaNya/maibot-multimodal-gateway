import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from gateway import app, subscriptions as subs

MESSAGES = [{'role': 'user', 'content': 'private prompt `$(echo no)`'}]

class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(app, 'STATE', Path(self.temp.name) / '.state')
        self.patch.start()
    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()
    def test_environment_and_policy(self):
        with patch.dict(os.environ, {'XAI_API_KEY': 'billing-secret', 'GOOGLE_API_KEY': 'secret'}):
            env = subs.prepare('gemini')
        self.assertNotIn('XAI_API_KEY', env)
        self.assertNotIn('GOOGLE_API_KEY', env)
        self.assertFalse((app.STATE / 'gemini/.gemini/settings.json').exists())
        subs.prepare('grok')
        self.assertIn('disable_api_key_auth = true', (app.STATE / 'grok/config.toml').read_text())
    def test_cli_formats_and_private_input(self):
        for provider in ('chatgpt', 'grok'):
            with self.subTest(provider=provider), patch.object(subs, 'executable', side_effect=lambda x: '/bin/' + x), patch.object(subs, 'run_bounded', return_value=json.dumps({'text': 'hello', 'response': 'hello'})) as run:
                self.assertEqual(subs.generate(provider, 'test-model', MESSAGES), 'hello')
                command = run.call_args.args[0]
                self.assertNotIn(MESSAGES[0]['content'], ' '.join(command))
                if provider == 'grok':
                    self.assertIn('--prompt-file', command)
                    self.assertIn('MCPTool', command)
                if provider == 'gemini':
                    self.assertEqual(run.call_args.kwargs['payload'], MESSAGES)
    def test_runtime_uses_stdio_and_cleans_up_timeout(self):
        raw = subs.run_bounded([sys.executable, '-c', 'import sys,json; print(json.dumps({"text":json.load(sys.stdin)["text"]}))'], os.environ.copy(), {'text': 'hello'})
        self.assertEqual(json.loads(raw)['text'], 'hello')
        with self.assertRaises(app.Failure) as caught:
            subs.run_bounded([sys.executable, '-c', 'import time; time.sleep(3)'], os.environ.copy(), timeout=0.05)
        self.assertEqual(caught.exception.status, 504)
    def test_failed_runtime_no_raw_stderr(self):
        with self.assertRaises(app.Failure) as caught:
            subs.run_bounded([sys.executable, '-c', 'import sys; sys.stderr.write("secret-token"); sys.exit(1)'], os.environ.copy())
        self.assertNotIn('secret-token', caught.exception.code)
    def test_gateway_routes_and_releases_slot_after_failure(self):
        gateway = app.Gateway('local')
        for provider in subs.PROVIDERS:
            with patch.object(subs, 'generate', return_value='subscription hello'):
                result = gateway.dispatch('/v1/chat/completions', {'model': provider + '/test-model', 'messages': MESSAGES})
                self.assertEqual(result['choices'][0]['message']['content'], 'subscription hello')
            if provider != 'grok':
                with self.assertRaises(app.Failure) as caught:
                    gateway.dispatch('/v1/images/generations', {'model': provider + '/image', 'prompt': 'apple'})
                self.assertEqual(caught.exception.status, 403)
        with patch.object(subs, 'generate', side_effect=app.Failure(403, 'denied')):
            with self.assertRaises(app.Failure):
                gateway.dispatch('/v1/chat/completions', {'model': 'chatgpt/test', 'messages': MESSAGES})
        self.assertTrue(gateway.slots.acquire(blocking=False))
        gateway.slots.release()
    def test_invalid_model_and_missing_runtime(self):
        with self.assertRaises(app.Failure):
            subs.generate('grok', '--yolo', MESSAGES)
        with patch.object(subs.shutil, 'which', return_value=None), self.assertRaises(app.Failure) as caught:
            subs.executable('grok')
        self.assertEqual(caught.exception.code, 'grok_not_installed')
