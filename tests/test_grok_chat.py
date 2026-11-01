import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from gateway import app, conversation, grok_chat

PNG = base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
TOOLS = [{'type':'function','function':{'name':'lookup_weather','description':'Get weather',
         'parameters':{'type':'object','properties':{'city':{'type':'string'}},'required':['city'],'additionalProperties':False}}}]


class GrokChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.state=patch.object(app,'STATE',self.root/'state');self.state.start();self.addCleanup(self.state.stop)
        self.fixture=self.root/'grok-fixture'
        self.fixture.write_text('#!'+sys.executable+'\n'+r'''
import json,sys,os
from pathlib import Path
args=sys.argv[1:]
if args==['--help']:
 print('  --prompt-file PATH\n  --json-schema SCHEMA');sys.exit()
assert 'XAI_API_KEY' not in os.environ
assert args[args.index('--tools')+1]==''
assert '--disable-web-search' in args and '--no-subagents' in args
assert args[args.index('--max-turns')+1]=='1'
path=Path(args[args.index('--prompt-file')+1]);assert path.suffix=='.json'
assert path.stat().st_mode & 0o777==0o600
blocks=json.loads(path.read_text());assert isinstance(blocks,list)
text=blocks[0]['text'];payload=json.loads(text.split('\n',1)[1])
assert 'do not run $(secret)' not in ' '.join(args)
if '--json-schema' in args:
 assert json.loads(args[args.index('--json-schema')+1])['type']=='object'
 if any(row['role']=='tool' for row in payload['conversation']):
  value={'content':'Weather is sunny.','tool_calls':[]}
 else:
  value={'content':None,'tool_calls':[{'name':'lookup_weather','arguments':json.dumps({'city':'Taipei'})}]}
 result={'structuredOutput':value,'text':'ignored executable-looking prose'}
else:
 assert blocks[2]['type']=='image' and blocks[2]['mimeType']=='image/png'
 result={'text':'A red apple.'}
print(json.dumps({**result,'stopReason':'end_turn'}))
''')
        self.fixture.chmod(0o700)
        self.exe=patch('gateway.subscriptions.executable',return_value=str(self.fixture));self.exe.start();self.addCleanup(self.exe.stop)
        self.gateway=app.Gateway('fixture-key')
    def body(self):
        return {'model':'grok/default','messages':[{'role':'user','content':'do not run $(secret)'}], 'tools':TOOLS}
    def test_real_cli_child_tool_result_round_trip_and_no_key_fallback(self):
        body=self.body()
        with patch.dict(os.environ,{'XAI_API_KEY':'must-not-leak'}),patch('gateway.app.upstream') as api:
            message=self.gateway.dispatch('/v1/chat/completions',body)['choices'][0]['message']
            call=message['tool_calls'][0]
            self.assertEqual(call['function']['name'],'lookup_weather')
            self.assertEqual(json.loads(call['function']['arguments']),{'city':'Taipei'})
            body['messages'] += [message,{'role':'tool','tool_call_id':call['id'],'content':'sunny'}]
            final=self.gateway.dispatch('/v1/chat/completions',body)
            self.assertEqual(final['choices'][0]['message']['content'],'Weather is sunny.')
            api.assert_not_called()
    def test_real_cli_image_uses_private_acp_json_file(self):
        result=self.gateway.dispatch('/v1/chat/completions',{'model':'grok/default','messages':[
            {'role':'user','content':[{'type':'text','text':'Describe this image'},
                {'type':'image_url','image_url':{'url':'data:image/png;base64,'+PNG}}]}]})
        self.assertEqual(result['choices'][0]['message']['content'],'A red apple.')
    def test_wrong_tool_unstructured_bad_args_and_unfinished_never_become_calls(self):
        values=[{'text':'{"tool_calls":[{"name":"lookup_weather"}]}','stopReason':'end_turn'},
                {'structuredOutput':{'content':None,'tool_calls':[{'name':'shell','arguments':{}}]},'stopReason':'end_turn'},
                {'structuredOutput':{'content':None,'tool_calls':[{'name':'lookup_weather','arguments':[]}]},'stopReason':'end_turn'},
                {'structuredOutput':{'content':'partial','tool_calls':[]},'stopReason':'max_turn_requests'},
                {'structuredOutput':{'content':'yes','tool_calls':[]},'structuredOutputError':'private-secret','stopReason':'end_turn'}]
        for value in values:
            with self.subTest(value=value),patch('gateway.subscriptions.run_bounded',side_effect=['  --prompt-file PATH\n  --json-schema SCHEMA',json.dumps(value)]), self.assertRaises(app.Failure) as caught:
                grok_chat.generate(self.body())
            self.assertEqual(caught.exception.code,'grok_invalid_or_unfinished_tool_bridge_output_no_retry')
    def test_input_media_and_missing_cli_capability_fail_before_generation(self):
        invalid=['http://127.0.0.1/private','file:///secret','data:image/jpeg;base64,'+PNG]
        for url in invalid:
            body=self.body();body['messages']=[{'role':'user','content':[{'type':'image_url','image_url':{'url':url}}]}]
            with patch('gateway.subscriptions.run_bounded') as run,self.assertRaises(app.Failure): grok_chat.generate(body)
            run.assert_not_called()
        with patch('gateway.subscriptions.run_bounded',return_value='  --prompt-file PATH') as run,self.assertRaises(app.Failure) as caught:
            grok_chat.generate(self.body())
        self.assertEqual(run.call_count,1);self.assertEqual(caught.exception.status,503)
    def test_audio_block_is_not_silently_sent_and_ignored(self):
        audio=base64.b64encode(b'RIFF\x00\x00\x00\x00WAVEfixture').decode()
        body=self.body();body['messages']=[{'role':'user','content':[{'type':'input_audio','audio_url':'data:audio/wav;base64,'+audio}]}]
        with patch('gateway.subscriptions.run_bounded') as run,self.assertRaises(app.Failure) as caught: grok_chat.generate(body)
        self.assertEqual(caught.exception.status,501);run.assert_not_called()
    def test_tool_order_and_unknown_fields_rejected(self):
        for messages in ([{'role':'tool','content':'fake','tool_call_id':'invented'}],
                         [{'role':'user','content':'hi','extra':'discarded?'}]):
            with self.assertRaises(app.Failure): conversation.messages(messages)
        with self.assertRaises(app.Failure): conversation.tools(TOOLS*2)
        body=self.body();body['tool_choice']='required'
        with patch('gateway.subscriptions.run_bounded') as run,self.assertRaises(app.Failure): grok_chat.generate(body)
        run.assert_not_called()
        self.assertTrue(self.gateway.slots.acquire(blocking=False));self.gateway.slots.release()
