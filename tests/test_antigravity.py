import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from gateway import app, antigravity, subscriptions

class AntigravityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.home_patch = patch.object(antigravity.Path, 'home', return_value=self.home)
        self.home_patch.start()
        self.config = self.home / '.gemini/antigravity-cli/settings.json'
        self.config.parent.mkdir(parents=True)
        self.config.write_text('{"toolPermission":"strict"}')
    def tearDown(self):
        self.home_patch.stop()
        self.temp.cleanup()
    def test_native_stream_and_no_legacy_cli(self):
        response = json.dumps({'event':'result','result':{'status':'SUCCESS','response':'hello'}})
        with patch.object(subscriptions,'executable',side_effect=lambda x:'/bin/'+x), patch.object(subscriptions,'run_bounded',return_value=response) as run:
            self.assertEqual(antigravity.generate('default',[{'role':'user','content':'private text'}],{}),'hello')
            command = run.call_args.args[0]
            self.assertEqual(command[0],'/bin/agy')
            self.assertNotIn('private text',' '.join(command))
            self.assertNotIn('--dangerously-skip-permissions',command)
            self.assertIn('--disable-slash-commands',command)
            self.assertEqual(run.call_args.kwargs['payload']['event'],'user')
    def test_unsafe_or_billable_settings_rejected_without_mutation(self):
        for settings in ({'toolPermission':'always-proceed'}, {'toolPermission':'strict','modelProvider':'gemini'}, {'toolPermission':'strict','gcp':{'project':'billable'}}):
            self.config.write_text(json.dumps(settings))
            original=self.config.read_bytes()
            with self.assertRaises(app.Failure):
                antigravity.checked_settings()
            self.assertEqual(self.config.read_bytes(),original)
    def test_shared_hooks_rejected(self):
        hooks=self.home/'.gemini/config/hooks.json'
        hooks.parent.mkdir()
        hooks.write_text('{"hooks":{"SessionStart":["command"]}}')
        with self.assertRaises(app.Failure) as caught:
            antigravity.checked_settings()
        self.assertEqual(caught.exception.code,'antigravity_shared_extensions_require_review')
    def test_text_still_requires_global_strict_without_a_session_overlay(self):
        for settings in (None, {}, {'toolPermission':'request-review'}):
            if settings is None:
                self.config.unlink()
            else:
                self.config.write_text(json.dumps(settings))
            with patch.object(subscriptions,'run_bounded') as run, self.assertRaises(app.Failure) as caught:
                antigravity.generate('default',[],{})
            self.assertEqual(caught.exception.code,'antigravity_set_toolPermission_strict_in_config')
            run.assert_not_called()
    def test_failed_or_missing_result_not_text_success(self):
        for response in ('{"event":"init"}', '{"event":"result","result":{"status":"ERROR","response":"not success"}}'):
            with patch.object(subscriptions,'executable',return_value='/bin/agy'), patch.object(subscriptions,'run_bounded',return_value=response), self.assertRaises(app.Failure):
                antigravity.generate('default',[],{})
