import json
import os
from pathlib import Path
import tempfile
import unittest
from gateway.media_diagnostics import summarize_failure, cached_image_failure, cached_media_failure

class DiagnosticTests(unittest.TestCase):
    def test_video_native_errors_are_distinguished_and_redacted(self):
        cases = [
            ({'details': {'code': 'zdr_output_storage_required'}}, 'video_zdr_storage_required'),
            ('Video generation tools are unavailable under zero data retention (ZDR). private', 'video_zdr_storage_required'),
            ('image reference not readable: /private/secret.png (missing)', 'video_source_image_invalid'),
            ('duration must be either 6 or 10 seconds. Got 8.', 'invalid_tool_arguments'),
            ('`resolution_name` must be one of: 480p. Got secret.', 'invalid_tool_arguments'),
            ('Video generation request expired (request_id=secret).', 'video_request_expired'),
            ('Video generation did not complete within 600s (request_id=secret)', 'video_poll_timeout'),
            ('Video generation failed on the server (request_id=secret): private', 'video_server_generation_failed'),
            ('Video generation completed but no download URL was returned.', 'video_response_incomplete'),
        ]
        for value, category in cases:
            with self.subTest(category=category):
                result = summarize_failure(value)
                self.assertEqual(result['category'], category)
                self.assertNotIn('secret', json.dumps(result))
                self.assertNotIn('private', json.dumps(result))

    def test_video_cached_failure_selects_video_not_starting_image(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root/'session/updates.jsonl'; path.parent.mkdir()
            entries = [
                {'type':'tool_call','toolCallId':'1','toolName':'image_gen'},
                {'type':'tool_call_update','toolCallId':'1','status':'completed'},
                {'update':{'sessionUpdate':'tool_call','toolCallId':'2','title':'image_to_video: private'}},
                {'update':{'sessionUpdate':'tool_call_update','toolCallId':'2','status':'failed',
                    'rawOutput':{'error':{'details':{'code':'zdr_output_storage_required'},'message':'private'}}}},
            ]
            path.write_text('\n'.join(map(json.dumps, entries)))
            result = cached_media_failure(root, 'video')
            self.assertEqual(result['requested_tool'], 'image_to_video')
            self.assertEqual(result['failure']['category'], 'video_zdr_storage_required')
            self.assertTrue(result['found'])
            self.assertFalse(cached_media_failure(root, 'image')['found'])
            self.assertNotIn('private', json.dumps(result))

    def test_new_success_does_not_return_stale_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for n, status in enumerate(('failed', 'completed')):
                path = root/str(n)/'updates.jsonl'; path.parent.mkdir()
                path.write_text('\n'.join(map(json.dumps, [
                    {'type':'tool_call','toolCallId':'1','toolName':'image_to_video'},
                    {'type':'tool_call_update','toolCallId':'1','status':status,'rawOutput':'HTTP 403 secret'},
                ])))
                os.utime(path, ns=(1000000000+n, 1000000000+n))
            result = cached_media_failure(root, 'video')
            self.assertFalse(result['found'])
            self.assertEqual(result['latest_tool_status'], 'completed')
            self.assertNotIn('failure', result)

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
