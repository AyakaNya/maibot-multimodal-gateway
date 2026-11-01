import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from gateway import app, codex_images, subscription_images as images, subscriptions

PNG = b'\x89PNG\r\n\x1a\nimage-fixture'
THREAD = '00000000-0000-4000-8000-000000000001'


def stream(*events):
    return '\n'.join(map(json.dumps, events))


class FakeRpc:
    account = {'type': 'chatgpt', 'planType': 'plus'}
    item = {'id':'image-1', 'type':'imageGeneration', 'status':'completed',
            'result':base64.b64encode(PNG).decode()}

    def __init__(self, command, env, work):
        self.requests = []
        self.closed = False
        self.events = iter([
            {'method':'item/completed','params':{'threadId':THREAD,'item':self.item}},
            {'method':'turn/completed','params':{'threadId':THREAD,'turn':{'status':'completed'}}}])
    def request(self, method, params):
        self.requests.append((method, params))
        if method == 'account/read':
            return {'account':self.account}
        if method == 'thread/start':
            return {'thread':{'id':THREAD}}
        return {}
    def send(self, value):
        pass
    def receive(self):
        return next(self.events)
    def reject_request(self, event):
        pass
    def close(self):
        self.closed = True


class SubscriptionImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state_patch = patch.object(app, 'STATE', self.root/'.state')
        self.state_patch.start()
        self.home_patch = patch.object(Path, 'home', return_value=self.root)
        self.home_patch.start()
        self.config = self.root/'.gemini/antigravity-cli/settings.json'
        self.config.parent.mkdir(parents=True)
        self.config.write_text('{"toolPermission":"strict"}')
        self.work = self.root/'work'; self.work.mkdir()
    def tearDown(self):
        self.home_patch.stop()
        self.state_patch.stop()
        self.temp.cleanup()
    def gemini_events(self, error=None):
        info = {'name':'generate_image', 'output':'private prompt secret-token'}
        if error:
            info['error'] = error
        return stream(
            {'event':'init','conversation_id':THREAD,'init':{'tools':['generate_image']}},
            {'event':'step_update','step_update':{'step_type':'tool','step_index':1,
                'tool_name':'generate_image','state':'ACTIVE'}},
            {'event':'step_update','step_update':{'step_type':'tool','step_index':1,
                'tool_name':'generate_image','state':'DONE','tool_info':info}},
            {'event':'result','result':{'status':'SUCCESS','response':'private prompt secret-token'}})
    def artifact(self, thread=THREAD):
        p = self.root/'.gemini/antigravity-cli/brain'/thread/'generated.png'
        p.parent.mkdir(parents=True, exist_ok=True);p.write_bytes(PNG)
        return p
    def test_router_concurrency_and_no_api_fallback(self):
        gateway = app.Gateway('local')
        for provider in ('chatgpt', 'gemini'):
            body = {'model':provider+'/default','prompt':'apple'}
            with patch.object(images,'generate',return_value={'data':[]}) as generate:
                self.assertEqual(gateway.dispatch('/v1/images/generations',body),{'data':[]})
                generate.assert_called_once_with(body)
            with patch.object(images,'generate',side_effect=app.Failure(403,'denied')), patch.object(app,'upstream') as upstream:
                with self.assertRaises(app.Failure):
                    gateway.dispatch('/v1/images/generations',body)
                upstream.assert_not_called()
            self.assertTrue(gateway.slots.acquire(False))
            with patch.object(images,'generate') as generate, self.assertRaises(app.Failure) as caught:
                gateway.dispatch('/v1/images/generations',body)
            self.assertEqual(caught.exception.code,'gateway_busy')
            generate.assert_not_called();gateway.slots.release()
    def test_validation_before_runtime(self):
        cases = ({'n':True},{'n':2},{'size':'1024x1024'},{'prompt':' '},{'model':'chatgpt/gpt-image-2'},{'image':'/secret'})
        for extra in cases:
            with self.subTest(extra=extra), patch.object(images,'codex_environment') as prepare, self.assertRaises(app.Failure):
                images.generate({'model':'chatgpt/default','prompt':'apple',**extra})
            prepare.assert_not_called()
    def test_isolated_codex_login_config_and_api_environment(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'secret','CODEX_HOME':'/unrelated',
                'CODEX_CONFIG':'private','GEMINI_API_KEY':'secret','AGY_ADC_AUTH':'true','GOOGLE_APPLICATION_CREDENTIALS':'/secret'}):
            env = images.codex_environment()
        self.assertEqual(Path(env['CODEX_HOME']),app.STATE/'codex-images')
        for key in ('OPENAI_API_KEY','GEMINI_API_KEY','AGY_ADC_AUTH','CODEX_CONFIG','GOOGLE_APPLICATION_CREDENTIALS'):
            self.assertNotIn(key,env)
        config = app.STATE/'codex-images/config.toml'
        self.assertEqual(config.stat().st_mode & 0o777,0o600)
        self.assertIn('forced_login_method = "chatgpt"',config.read_text())
        self.assertIn('shell_tool = false',config.read_text())
    def test_codex_native_item_and_login_guard(self):
        instances=[]
        def factory(*args):
            rpc=FakeRpc(*args);instances.append(rpc);return rpc
        env={'CODEX_HOME':str(app.STATE/'codex-images')}
        with patch.object(subscriptions,'executable',return_value='/bin/codex'):
            result=codex_images.generate('private prompt',env,rpc_factory=factory)
        self.assertEqual(base64.b64decode(result['b64_json']),PNG)
        self.assertTrue(instances[0].closed)
        params=dict(instances[0].requests)['thread/start']
        self.assertEqual(params['sandbox'],'read-only')
        with patch.object(FakeRpc,'account',{'type':'apiKey'}), patch.object(subscriptions,'executable',return_value='/bin/codex'), self.assertRaises(app.Failure) as caught:
            codex_images.generate('apple',env,rpc_factory=factory)
        self.assertEqual(caught.exception.code,'codex_images_require_chatgpt_login')
        self.assertNotIn('turn/start',dict(instances[-1].requests))
        self.assertTrue(instances[-1].closed)
    def test_codex_tool_failure_redacted_and_not_retried(self):
        item={'id':'x','type':'imageGeneration','status':'failed',
              'failure':{'message':'HTTP 403 private prompt Bearer secret-token'}}
        with patch.object(FakeRpc,'item',item), patch.object(subscriptions,'executable',return_value='/bin/codex'), self.assertRaises(app.Failure) as caught:
            codex_images.generate('apple',{'CODEX_HOME':str(self.root)},rpc_factory=FakeRpc)
        self.assertEqual(caught.exception.code,'codex_image_tool_failed')
        summary=app.read_secret('subscription-image-diagnostic.json')
        self.assertIn('api_forbidden',summary)
        for secret in ('private prompt','secret-token','Bearer'):
            self.assertNotIn(secret,summary)
    def test_codex_saved_paths_are_scoped_to_own_artifacts(self):
        own=self.work/'generated_images/one.png';own.parent.mkdir();own.write_bytes(PNG)
        codex_images.image_result({'savedPath':str(own)},app.STATE,THREAD,self.work)
        other=self.root/'other.png';other.write_bytes(PNG)
        for item in ({'savedPath':str(other)},{'result':'https://private.test/image.png'},{'text':str(own)}):
            with self.assertRaises(app.Failure):
                codex_images.image_result(item,app.STATE,THREAD,self.work)
    def test_codex_inline_and_saved_images_with_macos_ancestor_alias(self):
        real=self.root/'private-var';real.mkdir()
        alias=self.root/'var';alias.symlink_to(real,target_is_directory=True)
        workspace=alias/'work';workspace.mkdir()
        item={'result':base64.b64encode(PNG).decode()}
        result=codex_images.image_result(item,app.STATE,THREAD,workspace)
        self.assertEqual(base64.b64decode(result['b64_json']),PNG)
        for path in (workspace/'generated.png',(workspace/'generated.png').resolve()):
            result=codex_images.image_result({'savedPath':str(path)},app.STATE,THREAD,workspace)
            self.assertEqual(base64.b64decode(result['b64_json']),PNG)
    def test_codex_diagnostic_distinguishes_completed_tool_from_collected_artifact(self):
        with patch.object(subscriptions,'executable',return_value='/bin/codex'), patch.object(codex_images,'image_result',side_effect=app.Failure(502,'unsafe_media_path')), self.assertRaises(app.Failure):
            codex_images.generate('private prompt',{'CODEX_HOME':str(self.root)},rpc_factory=FakeRpc)
        summary=json.loads(app.read_secret('subscription-image-diagnostic.json'))
        self.assertTrue(summary['tool_completed'])
        self.assertFalse(summary['artifact_collected'])
        self.assertEqual(summary['artifact_error'],'unsafe_media_path')
        for secret in ('private prompt',str(self.root)):
            self.assertNotIn(secret,json.dumps(summary))
        with patch.object(subscriptions,'executable',return_value='/bin/codex'):
            codex_images.generate('apple',{'CODEX_HOME':str(self.root)},rpc_factory=FakeRpc)
        self.assertTrue(json.loads(app.read_secret('subscription-image-diagnostic.json'))['artifact_collected'])
    def test_gemini_uses_native_tool_and_current_session(self):
        self.artifact()
        result=images.collect_gemini(self.gemini_events(),0,self.work)
        self.assertEqual(base64.b64decode(result['b64_json']),PNG)
        summary=app.read_secret('subscription-image-diagnostic.json')
        self.assertNotIn('secret-token',summary)
        self.assertNotIn('private prompt',summary)
    def test_gemini_failure_and_other_session_are_not_success(self):
        self.artifact('00000000-0000-4000-8000-000000000002')
        for raw,code in ((self.gemini_events(),0),(self.gemini_events({'message':'HTTP 429 Bearer secret'}),0),
                         (stream({'event':'result','result':{'status':'SUCCESS','response':'saved.png'}}),0),
                         (self.gemini_events(),1)):
            with self.assertRaises(app.Failure):
                images.collect_gemini(raw,code,self.work)
    def test_gemini_session_settings_do_not_modify_global_profile(self):
        original=self.config.read_bytes()
        def run(command,env,**kwargs):
            if '--help' in command:
                return '--settings --agent'
            overlay=json.loads(command[command.index('--settings')+1])
            self.assertEqual(overlay['toolPermission'],'request-review')
            self.assertFalse(overlay['useG1Credits'])
            self.assertIn('command(*)',overlay['permissions']['deny'])
            self.assertNotIn('--dangerously-skip-permissions',command)
            self.assertNotIn('private prompt',' '.join(command))
            agent=next((Path(kwargs['workdir'])/'.agents/agents').glob('*.md')).read_text()
            self.assertIn('  - generate_image',agent)
            self.assertIn('subagent: false',agent)
            (Path(kwargs['workdir'])/'generated.png').write_bytes(PNG)
            return 0,self.gemini_events()
        with patch.object(subscriptions,'executable',return_value='/bin/agy'), patch.object(subscriptions,'run_bounded',side_effect=run):
            images.generate({'model':'gemini/default','prompt':'private prompt'})
        self.assertEqual(self.config.read_bytes(),original)
    def test_gemini_old_cli_is_rejected_before_generation(self):
        with patch.object(subscriptions,'executable',return_value='/bin/agy'), patch.object(subscriptions,'run_bounded',return_value='old help') as run, self.assertRaises(app.Failure) as caught:
            images.generate({'model':'gemini/default','prompt':'apple'})
        self.assertEqual(caught.exception.code,'antigravity_update_cli_for_session_settings')
        self.assertEqual(run.call_count,1)
    def test_real_jsonl_rpc_and_timeout_cleanup(self):
        code = "import sys,json; q=json.loads(sys.stdin.readline()); print(json.dumps({'id':q['id'],'result':{'ok':True}}),flush=True)"
        rpc=codex_images.Rpc([sys.executable,'-c',code],{},str(self.work),timeout=2)
        try:
            self.assertEqual(rpc.request('initialize',{}),{'ok':True})
        finally: rpc.close()
        rpc=codex_images.Rpc([sys.executable,'-c','import time;time.sleep(5)'],{},str(self.work),timeout=0.05)
        try:
            with self.assertRaises(app.Failure) as caught: rpc.receive()
            self.assertEqual(caught.exception.status,504)
        finally: rpc.close()
        self.assertIsNotNone(rpc.proc.poll())


if __name__ == '__main__':
    unittest.main()
