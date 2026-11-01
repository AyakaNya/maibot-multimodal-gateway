import base64
import io
import json
import unittest
import urllib.error
from unittest.mock import patch
from gateway import app, direct_media as direct

PNG = b'\x89PNG\r\n\x1a\nfixture'
MP4 = b'\x00\x00\x00\x18ftypmp42fixture'

class Wire:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
    def open(self, request, timeout):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(response if isinstance(response, bytes) else json.dumps(response).encode())

class DirectMediaTests(unittest.TestCase):
    def test_image_and_edit_request_match_dsh(self):
        image = {'data': [{'b64_json': base64.b64encode(PNG).decode()}]}
        with patch.object(direct.oauth, 'access_token', return_value='owned-token'):
            wire = Wire([image, image])
            result = direct.generate('image', {'model':'grok-oauth/default', 'prompt':'apple', 'size':'1536x1024'}, transport=wire)
            self.assertEqual(base64.b64decode(result['data'][0]['b64_json']), PNG)
            first = wire.requests[0]
            self.assertEqual(first.full_url, 'https://api.x.ai/v1/images/generations')
            self.assertEqual(first.get_header('Authorization'), 'Bearer owned-token')
            self.assertEqual(json.loads(first.data)['aspect_ratio'], '3:2')
            ref = 'data:image/png;base64,' + base64.b64encode(PNG).decode()
            direct.generate('edit', {'model':'grok-oauth/default','prompt':'make green','images':[ref]}, transport=wire)
            self.assertTrue(wire.requests[1].full_url.endswith('/images/edits'))
            self.assertEqual(json.loads(wire.requests[1].data)['image'], {'type':'image_url','url':ref})
    def test_direct_text_video_polls_and_download_has_no_bearer(self):
        wire = Wire([{'request_id':'request/1'}, {'status':'pending'}, {'status':'done','video':{'url':'https://vidgen.x.ai/movie.mp4?sig=private'}}, MP4])
        with patch.object(direct.oauth, 'access_token', return_value='owned-token'):
            result = direct.generate('video', {'model':'grok-oauth/default','prompt':'apple','duration':6}, transport=wire, pause=0)
        self.assertEqual(base64.b64decode(result['data'][0]['b64_json']), MP4)
        self.assertNotIn('image', json.loads(wire.requests[0].data))
        self.assertEqual(wire.requests[1].full_url, 'https://api.x.ai/v1/videos/request%2F1')
        self.assertEqual(wire.requests[1].get_header('Authorization'), 'Bearer owned-token')
        self.assertIsNone(wire.requests[-1].get_header('Authorization'))
        self.assertNotIn('sig=private', json.dumps(result))
    def test_permission_denial_is_final(self):
        wire = Wire([urllib.error.HTTPError('https://api.x.ai',403,'private',{},None)])
        with patch.object(direct.oauth, 'access_token', return_value='owned-token'), self.assertRaises(app.Failure) as caught:
            direct.generate('image', {'model':'grok-oauth/default','prompt':'apple'}, transport=wire)
        self.assertEqual(caught.exception.status,403)
        self.assertEqual(len(wire.requests),1)
    def test_unapproved_download_host_and_input_urls_rejected(self):
        for url in ('http://vidgen.x.ai/a', 'https://127.0.0.1/a', 'https://vidgen.x.ai@evil.test/a', 'https://vidgen.x.ai:invalid/a'):
            with self.assertRaises(app.Failure):
                direct.download_url(url)
        with self.assertRaises(app.Failure):
            direct.reference('https://example.test/private.png')
    def test_terminal_and_timeout_states(self):
        for status in ('failed','expired','unknown'):
            with patch.object(direct.oauth, 'access_token', return_value='owned-token'), self.assertRaises(app.Failure):
                direct.generate('video',{'model':'grok-oauth/default','prompt':'apple'},transport=Wire([{'request_id':'1'},{'status':status}]),pause=0)
        with patch.object(direct.oauth, 'access_token', return_value='owned-token'), self.assertRaises(app.Failure) as caught:
            direct.generate('video',{'model':'grok-oauth/default','prompt':'apple'},transport=Wire([{'request_id':'1'}]),pause=0,max_wait=0)
        self.assertEqual(caught.exception.status,504)
