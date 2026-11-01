import json
from pathlib import Path
import tempfile
import unittest
from gateway.media_diagnostics import summarize_failure, cached_image_failure

class DiagnosticTests(unittest.TestCase):
    def test_native_http_error_is_redacted(self):
        result = summarize_failure({'error':{'message':'Image generation failed with HTTP 403 Forbidden: secret-token user prompt https://signed.test/a?sig=secret', 'details':{'code':'http_failure','status':403}}})
        self.assertEqual(result,{'category':'api_forbidden','http_statuses':[403],'error_codes':['http_failure']})
        for secret in ('secret-token','user prompt','https://','signed.test'):
            self.assertNotIn(secret,json.dumps(result))
    def test_credential_permissions_and_transport_are_separate(self):
        cases=[('this account\'s login is not an xAI credential','non_xai_login'),('no xAI credential available','missing_xai_credential'),('permission denied: /private/file','local_permission_denied'),('Image generation API request failed: TLS error','transport_failure')]
        for message, category in cases:
            self.assertEqual(summarize_failure({'message':message})['category'],category)
    def test_arbitrary_numbers_are_not_http_status(self):
        self.assertEqual(summarize_failure('a prompt has 403 apples; Bearer secret429')['http_statuses'],[])
        self.assertEqual(summarize_failure('HTTP 429 Too Many Requests')['category'],'api_rate_limited')
    def test_cached_enveloped_acp_updates_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            path=root/'encoded/session/updates.jsonl';path.parent.mkdir(parents=True)
            entries=[{'update':{'sessionUpdate':'tool_call','toolCallId':'1','title':'image_gen: private'
,'rawInput':{'prompt':'private'}}},
                {'update':{'sessionUpdate':'tool_call_update','toolCallId':'1','status':'failed','content':[{'content':{'type':'text','text':'Image generation failed with HTTP 401 Unauthorized: Bearer secret'}}]}}]
            path.write_text('\n'.join(json.dumps(item) for item in entries))
            result=cached_image_failure(root)
            self.assertTrue(result['found'])
            self.assertEqual(result['failure']['category'],'api_authentication_failed')
            self.assertNotIn('private',json.dumps(result))
            self.assertNotIn('secret',json.dumps(result))
            self.assertNotIn('encoded',json.dumps(result))
    def test_credentials_are_never_scanned(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'auth.json').write_text('secret')
            self.assertEqual(cached_image_failure(root)['logs_scanned'],0)
