import asyncio
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'maibot_plugin'))
sys.path.insert(0, str(ROOT))
from maibot_sdk.context import PluginContext, PluginPaths
from maibot_multimodal_gateway.plugin import create_plugin
from maibot_multimodal_gateway.client import GatewayClient, GatewayError, Settings, artifact, provider_messages
from gateway import app

PNG = b'\x89PNG\r\n\x1a\nimage-fixture'
MP4 = b'\x00\x00\x00\x18ftypmp42video-fixture'
KEY = 'local_test_key_private_1234567890'


def media_result(kind):
    data = PNG if kind == 'image' else MP4
    return {'data': [{'b64_json': base64.b64encode(data).decode(),
        'media_type': 'image/png' if kind == 'image' else 'video/mp4',
        'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}]}


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.key = self.root/'gateway.key'; self.key.write_text(KEY); self.key.chmod(0o600)
        self.server = app.server(app.Gateway(KEY), port=0)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01),daemon=True)
        self.thread.start()
        self.origin = f'http://127.0.0.1:{self.server.server_address[1]}'
        self.calls = []
        self.sent = True
        self.files_enabled = True
        self.file_status = 'sent'
        self.uploaded = None
        owner = self
        class UploadHandler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_PUT(self):
                owner.uploaded=self.rfile.read(int(self.headers['Content-Length']))
                raw=json.dumps({'file_ref':'local-asset'}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        self.file_server=ThreadingHTTPServer(('127.0.0.1',0),UploadHandler)
        self.file_thread=threading.Thread(target=lambda:self.file_server.serve_forever(poll_interval=0.01),daemon=True)
        self.file_thread.start()
        async def rpc(method,plugin_id,payload,**kwargs):
            self.assertEqual(method,'cap.call')
            capability=payload['capability'];args=payload['args']
            self.calls.append((capability,args))
            if capability.startswith('send.'):
                return {'success':self.sent,'message_id':'local-message' if self.sent else None}
            if capability=='files.list':
                if not self.files_enabled: raise PermissionError('file service is disabled')
                return []
            if capability=='files.upload':
                return {'file_ref':'local-asset','upload_token':'local-ticket','max_bytes':32*1024*1024,
                        'url':f'http://127.0.0.1:{self.file_server.server_address[1]}/upload'}
            if capability=='files.send':
                return {'status':self.file_status,'message_id':'local-video'}
            raise AssertionError('unexpected capability')
        self.plugin=create_plugin()
        self.plugin._set_context(PluginContext('ayakanya.multimodal-gateway',rpc,
            PluginPaths(self.root/'data',self.root/'runtime')))
        config=self.plugin.get_default_config()
        config['plugin']['enabled']=True
        config['gateway'].update(base_url=self.origin,key_file=str(self.key))
        config['access'].update(allowed_stream_ids=['test-stream'],cooldown_seconds=0)
        config['features'].update(tools_enabled=True,video_enabled=True,llm_provider_enabled=True)
        self.plugin.set_plugin_config(config)
    async def asyncTearDown(self):
        await self.plugin.on_unload()
        pending=self.plugin._pending
        if pending is not None: await pending
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.file_server.shutdown();self.file_server.server_close();self.file_thread.join()
        self.temp.cleanup()
    async def command(self,arguments,**kwargs):
        return await self.plugin.command(stream_id='test-stream',platform='internal',
                     matched_groups={'arguments':arguments},**kwargs)
    def test_real_sdk_component_manifest_and_config_contract(self):
        manifest=json.loads((ROOT/'maibot_plugin/maibot_multimodal_gateway/_manifest.json').read_text())
        self.assertEqual({p['client_type'] for p in manifest['llm_providers']},
                         {p['client_type'] for p in self.plugin.get_llm_providers()})
        components=self.plugin.get_components()
        self.assertEqual({c['name'] for c in components},{'mm','gateway_image','gateway_video'})
        command=next(c for c in components if c['name']=='mm')
        matched=re.fullmatch(command['metadata']['command_pattern'],'/mm image gpt 一隻貓')
        self.assertEqual(matched.group('arguments'),'image gpt 一隻貓')
        for component in components:
            self.assertEqual(component['metadata']['timeout_ms'],660000)
            if component['type']=='TOOL':
                self.assertEqual(component['metadata']['platforms'],['internal'])
                for parameter in component['metadata']['parameters']: self.assertTrue(parameter['required'])
        defaults=self.plugin.get_default_config()
        self.assertFalse(defaults['plugin']['enabled'])
        self.assertFalse(defaults['features']['tools_enabled'])
        self.assertEqual(defaults['access']['allowed_stream_ids'],[])
        self.assertTrue(self.plugin.get_webui_config_schema())
    async def test_lifecycle_does_not_start_network_or_login(self):
        with patch.object(GatewayClient,'request') as request:
            await self.plugin.on_load()
            await self.plugin.on_config_update('self',self.plugin.get_plugin_config_data(),'0.1.0')
            request.assert_not_called()
    async def test_text_command_real_loopback_and_real_sdk_send(self):
        with patch('gateway.subscriptions.generate',return_value='hello') as upstream:
            result=await self.command('chat grok private prompt')
        self.assertTrue(result[0])
        self.assertEqual(upstream.call_count,1)
        self.assertEqual(self.calls[-1],('send.text',{'text':'hello','stream_id':'test-stream','return_details':True}))
        self.assertNotIn(KEY,json.dumps(self.calls))
    async def test_image_command_all_subscription_providers_and_checksum(self):
        for provider in ('grok','gpt','gemini'):
            with patch('gateway.media.generate',return_value=media_result('image')),patch('gateway.subscription_images.generate',return_value=media_result('image')):
                result=await self.command(f'image {provider} draw an apple')
            self.assertTrue(result[0])
            capability,args=self.calls[-1]
            self.assertEqual(capability,'send.image')
            self.assertEqual(base64.b64decode(args['image_base64']),PNG)
            self.assertEqual(args['stream_id'],'test-stream')
        bad=media_result('image');bad['data'][0]['sha256']='0'*64
        self.calls.clear()
        with patch('gateway.subscription_images.generate',return_value=bad):
            result=await self.command('image gpt apple')
        self.assertFalse(result[0])
        self.assertFalse(any(name=='send.image' for name,_ in self.calls))
    async def test_authorization_qq_disabled_and_unauthorized_stream_never_generate(self):
        with patch.object(GatewayClient,'request') as request:
            result=await self.plugin.command(stream_id='test-stream',platform='qq',matched_groups={'arguments':'image gpt apple'})
            self.assertFalse(result[0]);self.assertEqual(self.calls,[])
            result=await self.plugin.image_tool('gpt','apple',stream_id='other',platform='internal')
            self.assertFalse(result['success'])
            self.plugin.config.features.tools_enabled=False
            result=await self.plugin.image_tool('gpt','apple',stream_id='test-stream',platform='internal')
            self.assertFalse(result['success'])
            request.assert_not_called()
    async def test_status_discovers_stream_without_enabled_generation(self):
        self.plugin.config.plugin.enabled=False
        result=await self.command('status')
        self.assertTrue(result[0])
        self.assertIn('test-stream',self.calls[-1][1]['text'])
        self.assertNotIn(str(self.key),self.calls[-1][1]['text'])
    async def test_provider_current_context_and_legacy_text(self):
        modern={'item_schema_version':1,'context_items':[
            {'item_type':'SystemMessageItem','parts':[{'type':'text','text':'Be brief.'}]},
            {'item_type':'UserMessageItem','parts':[{'type':'text','text':'Hello'}]}],
            'model_info':{'model_identifier':'grok/default'},'tool_options':[]}
        with patch('gateway.subscriptions.generate',return_value='hello') as upstream:
            result=await self.plugin.llm_provider('response',modern)
        self.assertEqual(upstream.call_args.args[2],[{'role':'system','content':'Be brief.'},{'role':'user','content':'Hello'}])
        self.assertEqual(result['item_schema_version'],1)
        self.assertEqual(result['output_items'][0]['parts'][0]['text'],'hello')
        legacy={'message_list':[{'role':'user','content':'Hello'}],'model_info':{'model_identifier':'chatgpt/default'}}
        with patch('gateway.subscriptions.generate',return_value='legacy'):
            self.assertEqual(await self.plugin.llm_provider('response',legacy),{'content':'legacy'})
    async def test_provider_unsupported_inputs_fail_before_http(self):
        good={'model_info':{'model_identifier':'grok/default'},'message_list':[{'role':'user','content':'Hi'}]}
        cases=[('embedding',good),('response',{**good,'tool_options':[{'name':'reply'}]}),
               ('response',{**good,'message_list':[{'role':'user','content':[{'type':'image'}]}]}),
               ('response',{**good,'model_info':{'model_identifier':'openai/gpt-image-1'}}),
               ('response',{**good,'context_items':[{'item_type':'FunctionCallItem'}],'item_schema_version':1})]
        with patch.object(GatewayClient,'request') as request:
            for operation,body in cases:
                with self.assertRaises(GatewayError): await self.plugin.llm_provider(operation,body)
            request.assert_not_called()
    async def test_video_uses_real_sdk_upload_and_tool_scope_send(self):
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with patch('gateway.media.generate',return_value=media_result('video')) as upstream,patch('maibot_sdk.capabilities.files.urlopen',side_effect=opener.open):
            result=await self.plugin.video_tool('a lake',stream_id='test-stream',platform='internal')
        self.assertTrue(result['success'])
        self.assertEqual(upstream.call_count,1)
        self.assertEqual(self.uploaded,MP4)
        self.assertEqual([name for name,_ in self.calls],['files.list','files.upload','files.send'])
        self.assertNotIn(str(self.root),json.dumps(self.calls))
        self.assertEqual(list((self.root/'runtime').iterdir()),[])
    async def test_video_disabled_file_service_is_rejected_before_spending_quota(self):
        self.files_enabled=False
        with patch.object(GatewayClient,'request') as request:
            result=await self.plugin.video_tool('a lake',stream_id='test-stream',platform='internal')
            request.assert_not_called()
        self.assertFalse(result['success'])
        self.assertIn('video_requires_host_file_service',result['content'])
    async def test_video_unknown_delivery_is_not_retried(self):
        self.file_status='unknown'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with patch('gateway.media.generate',return_value=media_result('video')) as upstream,patch('maibot_sdk.capabilities.files.urlopen',side_effect=opener.open):
            result=await self.plugin.video_tool('a lake',stream_id='test-stream',platform='internal')
        self.assertFalse(result['success'])
        self.assertIn('do_not_regenerate',result['content'])
        self.assertEqual(upstream.call_count,1)
        self.assertEqual(sum(name=='files.send' for name,_ in self.calls),1)
    async def test_cancelled_http_keeps_busy_slot_until_original_worker_finishes(self):
        started=threading.Event();release=threading.Event()
        def slow(*args):
            started.set();release.wait(3);return {'status':'ok'}
        with patch.object(GatewayClient,'request',side_effect=slow):
            caller=asyncio.create_task(self.plugin._request('status'))
            self.assertTrue(await asyncio.to_thread(started.wait,1))
            worker=self.plugin._pending
            caller.cancel()
            with self.assertRaises(asyncio.CancelledError): await caller
            with self.assertRaises(GatewayError) as caught: await self.plugin._request('status')
            self.assertEqual(caught.exception.code,'plugin_busy')
            release.set();await worker;await asyncio.sleep(0)
            self.assertIsNone(self.plugin._pending)
    async def test_http_auth_error_and_false_delivery_are_not_success(self):
        self.key.write_text('wrong_gateway_key_1234567890')
        result=await self.command('chat grok hello')
        self.assertFalse(result[0])
        self.assertIn('invalid_gateway_key',self.calls[-1][1]['text'])
        self.assertNotIn('wrong_gateway_key',self.calls[-1][1]['text'])
        self.key.write_text(KEY);self.sent=False
        with patch('gateway.subscriptions.generate',return_value='hello') as upstream:
            result=await self.command('chat grok hello')
        self.assertFalse(result[0]);self.assertEqual(upstream.call_count,1)


class ClientTests(unittest.TestCase):
    def test_loopback_origin_and_subscriptions_only(self):
        for url in ('https://api.openai.com','http://localhost:8790','http://127.0.0.1:8790/v1',
                    'http://user:secret@127.0.0.1:8790','http://127.0.0.1:8790/?key=private'):
            with self.assertRaises(GatewayError): GatewayClient(Settings(url,'/key'))
    def test_rejects_unverified_or_mismatched_media(self):
        for field,value in (('bytes',True),('sha256','bad'),('media_type','video/mp4'),('b64_json','not-base64')):
            result=media_result('image');result['data'][0][field]=value
            with self.assertRaises(GatewayError): artifact(result,'image')
        with self.assertRaises(GatewayError): artifact({'data':[media_result('image')['data'][0]]*2},'image')
    def test_import_matches_actual_runner_package_loading(self):
        directory=ROOT/'maibot_plugin/maibot_multimodal_gateway'
        spec=importlib.util.spec_from_file_location('runner_gateway_reference',directory/'plugin.py',submodule_search_locations=[str(directory)])
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
        spec.loader.exec_module(module)
        self.assertEqual(module.create_plugin().get_llm_providers()[0]['client_type'],'ayakanya.multimodal_gateway')


if __name__=='__main__': unittest.main()
