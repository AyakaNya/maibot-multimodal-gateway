import base64
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from gateway import app, media, subscriptions

PNG=b'\x89PNG\r\n\x1a\nfixture'

def events(*items):
    return '\n'.join(json.dumps(item) for item in items)

def started():
    return {'type':'tool_call','toolCallId':'1','toolName':'image_gen'}

def done(path):
    return {'type':'tool_call_update','toolCallId':'1','status':'completed','rawOutput':{'path':str(path)}}

class EventTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.patch=patch.object(app,'STATE',self.root/'.state')
        self.patch.start()
        self.work=self.root/'work'; self.work.mkdir()
        self.sessions=self.root/'sessions'; self.sessions.mkdir()
    def tearDown(self):
        self.patch.stop(); self.temp.cleanup()
    def collect(self, raw, code=0):
        return media.collect_media(raw,code,'image',self.sessions,self.work,'this-session')
    def test_workspace_media_survives_collection_and_nonzero_end(self):
        path=self.work/'images/1.png'; path.parent.mkdir(); path.write_bytes(PNG)
        result=self.collect(events(started(),done(path),{'type':'max_turns_reached'}),code=1)
        self.assertEqual(base64.b64decode(result['b64_json']),PNG)
    def test_path_and_completion_can_arrive_in_separate_updates(self):
        path=self.work/'1.png'; path.write_bytes(PNG)
        self.collect(events(started(),{'type':'tool_call_update','toolCallId':'1','rawOutput':{'path':str(path)}}, {'type':'tool_call_update','toolCallId':'1','status':'completed'}))
    def test_specific_missing_tool_failures_and_redacted_diagnostics(self):
        cases=[
            (events({'type':'available_commands','tools':[]}), 'media_cli_tool_not_available'),
            (events({'type':'text','data':'private prompt Bearer secret https://secret.test'}), 'media_cli_tool_not_called'),
            (events(started(),{'type':'tool_call_update','toolCallId':'1','status':'failed','rawOutput':'Bearer private-token'}), 'media_cli_tool_failed'),
            (events(started()),'media_cli_tool_not_completed'),
            (events(started(),done(self.work/'missing.png')),'media_cli_output_file_not_found')]
        for raw, expected in cases:
            with self.subTest(expected=expected), self.assertRaises(app.Failure) as caught:
                self.collect(raw)
            self.assertEqual(caught.exception.code,expected)
            diagnostic=app.read_secret('media-diagnostic.json')
            for secret in ('private prompt','Bearer','private-token','https://secret.test'):
                self.assertNotIn(secret,diagnostic)
    def test_model_path_and_other_session_not_accepted(self):
        path=self.sessions/'other-session/images/1.png'; path.parent.mkdir(parents=True); path.write_bytes(PNG)
        with self.assertRaises(app.Failure):
            self.collect(events(started(),done(path)))
        with self.assertRaises(app.Failure):
            self.collect(events({'type':'text','data':json.dumps({'path':str(path)})}))
    def test_multiple_files_rejected(self):
        for name in ('1.png','2.png'):
            (self.work/name).write_bytes(PNG)
        with self.assertRaises(app.Failure) as caught:
            self.collect(events(started(),done(self.work/'1.png')))
        self.assertEqual(caught.exception.code,'media_multiple_artifacts')

    def test_real_child_workspace_and_nonzero_output_are_preserved(self):
        code = """import json, pathlib, sys
p=pathlib.Path.cwd()/'1.png'
p.write_bytes(bytes.fromhex('89504e470d0a1a0a')+b'fixture')
print(json.dumps({'type':'tool_call','toolCallId':'1','toolName':'image_gen'}))
print(json.dumps({'type':'tool_call_update','toolCallId':'1','status':'completed','rawOutput':{'path':str(p)}}))
sys.exit(1)
"""
        exit_code, raw = subscriptions.run_bounded([sys.executable,'-c',code],{},workdir=str(self.work),capture_exit=True)
        self.assertEqual(exit_code,1)
        self.assertTrue((self.work/'1.png').exists())
        self.assertEqual(base64.b64decode(self.collect(raw,exit_code)['b64_json']),PNG)

    def test_reported_no_tool_max_turn_requests_is_not_generic_not_called(self):
        raw=events({'type':'available_commands','tools':['image_gen']},
            {'type':'max_turns_reached'},
            {'type':'end','sessionId':'this-session','stopReason':'max_turn_requests'})
        with self.assertRaises(app.Failure) as caught:
            media.collect_media(raw,1,'image',self.sessions,self.work,'this-session',turn_budget=2)
        self.assertEqual(caught.exception.code,'media_cli_turn_limit_reached')
        diagnostic=json.loads(app.read_secret('media-diagnostic.json'))
        self.assertTrue(diagnostic['turn_limit_reached'])
        self.assertEqual(diagnostic['configured_turn_budget'],2)
        self.assertFalse(diagnostic['tool_called'])

    def test_turn_limit_after_completion_keeps_valid_image(self):
        path=self.work/'1.png';path.write_bytes(PNG)
        result=self.collect(events(started(),done(path),{'type':'end','stopReason':'max_turn_requests'}),code=1)
        self.assertEqual(base64.b64decode(result['b64_json']),PNG)

    def test_turn_budget_is_finite_and_invalid_values_do_not_run(self):
        with patch.dict(media.os.environ,{},clear=True):
            self.assertEqual(media.media_turn_budget('image'),8)
            self.assertEqual(media.media_turn_budget('video'),12)
        for value in ('0','17','unlimited','-1'):
            with patch.dict(media.os.environ,{'GATEWAY_GROK_MEDIA_MAX_TURNS':value}), self.assertRaises(app.Failure):
                media.media_turn_budget('image')
