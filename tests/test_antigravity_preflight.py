import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from gateway import app, antigravity, subscriptions, subscription_images
from gateway.antigravity_preflight import shared_extensions_report


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.home_patch=patch.object(Path,'home',return_value=self.root);self.home_patch.start()
        self.state_patch=patch.object(app,'STATE',self.root/'.state');self.state_patch.start()
        self.base=self.root/'.gemini/config';self.base.mkdir(parents=True)
        settings=self.root/'.gemini/antigravity-cli/settings.json';settings.parent.mkdir()
        settings.write_text('{}')
    def tearDown(self):
        self.state_patch.stop();self.home_patch.stop();self.temp.cleanup()
    def write(self,name,value):
        (self.base/name).write_text(json.dumps(value))
    def test_empty_hook_envelopes_and_metadata_are_not_active(self):
        for value in ({},{'hooks':{}},{'hooks':{'PreToolUse':[]}},
                      {'named-hook':{'SessionStart':[]}}, {'$schema':'private-url'}):
            self.write('hooks.json',value)
            with patch.object(subscriptions,'run_bounded') as run:
                result=shared_extensions_report()
            self.assertFalse(result['review_required'])
            self.assertFalse(result['generation_attempted'])
            self.assertNotIn('private-url',json.dumps(result))
            run.assert_not_called()
    def test_official_disabled_hooks_and_mcp_are_inactive(self):
        self.write('hooks.json',{'private-name':{'enabled':False,
                   'SessionStart':[{'command':'secret-command'}]}})
        self.write('mcp_config.json',{'mcpServers':{'private-server':{'disabled':True,
                   'command':'secret-executable','headers':{'Authorization':'Bearer secret'}}}})
        result=shared_extensions_report()
        self.assertFalse(result['review_required'])
        self.assertEqual(result['checks']['global_hooks']['disabled_group_count'],1)
        self.assertEqual(result['checks']['global_mcp']['disabled_server_count'],1)
        for secret in ('private-name','private-server','secret-command','secret-executable','Bearer'):
            self.assertNotIn(secret,json.dumps(result))
    def test_active_extensions_block_before_cli_and_report_only_fixed_counts(self):
        self.write('hooks.json',{'private-name':{'SessionStart':[{'command':'secret-command'}]}})
        self.write('mcp_config.json',{'mcpServers':{'private-server':{'command':'secret-executable'}}})
        with patch.object(subscriptions,'run_bounded') as run,self.assertRaises(app.Failure) as caught:
            subscription_images.generate({'model':'gemini/default','prompt':'private prompt'})
        self.assertEqual(caught.exception.code,'antigravity_shared_extensions_require_review')
        run.assert_not_called()
        result=json.loads(app.read_secret('subscription-image-diagnostic.json'))
        self.assertEqual(result['extension_checks']['global_hooks']['enabled_handler_count'],1)
        self.assertEqual(result['extension_checks']['global_mcp']['enabled_server_count'],1)
        for secret in ('private-name','private-server','secret-command','secret-executable','private prompt'):
            self.assertNotIn(secret,json.dumps(result))
    def test_unknown_invalid_oversized_and_linked_configs_stay_blocked(self):
        hooks=self.base/'hooks.json'
        for raw in ('{invalid secret','[]','{"unknown":"secret"}', ' '*(1024*1024+1), '['*2000+']'*2000):
            hooks.write_text(raw)
            self.assertTrue(shared_extensions_report()['review_required'])
        hooks.unlink()
        credentials=self.root/'auth-private.json';credentials.write_text('{"secret-token":"private"}')
        hooks.symlink_to(credentials)
        with patch('gateway.antigravity_preflight.json.loads',side_effect=AssertionError('symlink read')):
            result=shared_extensions_report()
        self.assertEqual(result['checks']['global_hooks']['state'],'symlink')
        self.assertNotIn('secret-token',json.dumps(result))
    def test_plugin_noise_is_ignored_real_installs_still_require_review(self):
        plugins=self.base/'plugins';plugins.mkdir()
        (plugins/'.DS_Store').write_bytes(b'not-json')
        (plugins/'README.md').write_text('private text')
        (plugins/'empty').mkdir()
        result=shared_extensions_report()
        self.assertFalse(result['review_required'])
        self.assertEqual(result['checks']['global_plugins']['ignored_entry_count'],3)
        installed=plugins/'private-plugin';installed.mkdir();(installed/'plugin.json').write_text('{}')
        result=shared_extensions_report()
        self.assertTrue(result['review_required'])
        self.assertEqual(result['checks']['global_plugins']['candidate_count'],1)
        self.assertNotIn('private-plugin',json.dumps(result))
    def test_mcp_disabled_must_be_boolean_true(self):
        for value in (False,'true',None):
            self.write('mcp_config.json',{'mcpServers':{'private-server':{'disabled':value,'command':'private'}}})
            self.assertTrue(shared_extensions_report()['review_required'])
    def test_inactive_shared_config_allows_image_session_without_modifying_it(self):
        self.write('hooks.json',{'hooks':{'SessionStart':[]}})
        self.write('mcp_config.json',{'mcpServers':{'private-server':{'disabled':True,'command':'private'}}})
        originals={path:path.read_bytes() for path in self.base.iterdir()}
        image=b'\x89PNG\r\n\x1a\nfixture'
        def run(command,env,**kwargs):
            if '--help' in command:
                return '--settings'
            (Path(kwargs['workdir'])/'generated.png').write_bytes(image)
            return 0,'\n'.join(map(json.dumps,[
                {'event':'init','init':{'tools':['generate_image']}},
                {'event':'step_update','step_update':{'step_type':'tool','step_index':1,
                     'tool_name':'generate_image','state':'DONE','tool_info':{}}},
                {'event':'result','result':{'status':'SUCCESS'}}]))
        with patch.object(subscriptions,'executable',return_value='/bin/agy'),patch.object(subscriptions,'run_bounded',side_effect=run):
            result=subscription_images.generate({'model':'gemini/default','prompt':'apple'})
        self.assertEqual(base64.b64decode(result['data'][0]['b64_json']),image)
        self.assertEqual({path:path.read_bytes() for path in self.base.iterdir()},originals)


if __name__ == '__main__':
    unittest.main()
