import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from gateway import app, media

PNG = b'\x89PNG\r\n\x1a\n' + b'test-image-fixture'
MP4 = b'\x00\x00\x00\x18ftypmp42' + b'test-video-fixture'

class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(app, 'STATE', Path(self.temp.name) / '.state')
        self.patch.start()
    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()
    def emit(self, kind):
        def run(command, env, **kwargs):
            self.assertNotIn('XAI_API_KEY', env)
            self.assertIn('MCPTool', command)
            denies = [command[index+1] for index, arg in enumerate(command) if arg == '--deny']
            self.assertIn('Edit(/**)', denies)
            self.assertIn('Write(/**)', denies)
            for lockdown in ('Edit', 'Write', 'Edit(*)', 'Write(*)'):
                self.assertNotIn(lockdown, denies)
            self.assertIn('Bash', denies)
            self.assertIn('Read', denies)
            self.assertIn('WebFetch', denies)
            self.assertNotIn('run_terminal_cmd', command[command.index('--tools')+1])
            session = command[command.index('--session-id')+1]
            folder = app.STATE / 'grok/sessions/encoded-cwd' / session / ('images' if kind == 'image' else 'videos')
            folder.mkdir(parents=True)
            (folder / ('1.png' if kind == 'image' else '1.mp4')).write_bytes(PNG if kind == 'image' else MP4)
            tool = 'image_gen' if kind == 'image' else 'image_to_video'
            path = folder / ('1.png' if kind == 'image' else '1.mp4')
            return 0, '\n'.join(json.dumps(event) for event in [
                {'type':'tool_call','toolCallId':'1','toolName':tool},
                {'type':'tool_call_update','toolCallId':'1','status':'completed','rawOutput':{'path':str(path)}},
                {'type':'end','stopReason':'end_turn'}])
        return run
    def test_image_and_video_output(self):
        for kind in ('image', 'video'):
            with patch('gateway.subscriptions.executable', return_value='/bin/grok'), patch('gateway.subscriptions.run_bounded', side_effect=self.emit(kind)):
                result = media.generate(kind, {'model': 'grok/default', 'prompt': 'an apple'})
                self.assertEqual(base64.b64decode(result['data'][0]['b64_json']), PNG if kind == 'image' else MP4)
                self.assertEqual(result['data'][0]['media_type'], 'image/png' if kind == 'image' else 'video/mp4')
    def test_cli_video_duration_contract(self):
        with patch('gateway.subscriptions.run_bounded') as run:
            for duration in (True, 1, 8, 15, '6'):
                with self.assertRaises(app.Failure) as caught:
                    media.generate('video', {'model':'grok/default', 'prompt':'apple', 'duration':duration})
                self.assertEqual(caught.exception.code, 'invalid_duration')
            run.assert_not_called()
        with patch('gateway.subscriptions.executable', return_value='/bin/grok'), patch('gateway.subscriptions.run_bounded', side_effect=self.emit('video')):
            media.generate('video', {'model':'grok/default', 'prompt':'apple', 'duration':10})
    def test_no_model_text_as_artifact(self):
        with patch('gateway.subscriptions.executable', return_value='/bin/grok'), patch('gateway.subscriptions.run_bounded', return_value=(0, '{"text":"Saved to /etc/passwd"}')):
            with self.assertRaises(app.Failure) as caught:
                media.generate('image', {'model': 'grok/default', 'prompt': 'apple'})
            self.assertEqual(caught.exception.code, 'media_cli_stream_format_unsupported')
    def test_symlink_and_invalid_file_rejected(self):
        folder = Path(self.temp.name) / 'media'
        folder.mkdir()
        external = Path(self.temp.name) / 'external.png'
        external.write_bytes(PNG)
        (folder / 'link.png').symlink_to(external)
        with self.assertRaises(app.Failure):
            media.read_artifact(folder / 'link.png', folder, 'image')
        (folder / 'not.png').write_text('not an image')
        with self.assertRaises(app.Failure):
            media.read_artifact(folder / 'not.png', folder, 'image')
    def test_provider_limit_and_audio(self):
        gateway = app.Gateway('test')
        with patch('gateway.subscriptions.run_bounded') as run:
            for provider in ('chatgpt', 'gemini'):
                with self.assertRaises(app.Failure):
                    media.generate('video', {'model': provider+'/default', 'prompt': 'apple'})
            with self.assertRaises(app.Failure) as caught:
                gateway.dispatch('/v1/audio/speech', {'model': 'grok/default', 'input': 'hello'})
            self.assertEqual(caught.exception.status, 501)
            run.assert_not_called()
    def test_gateway_routes_and_releases_slot(self):
        gateway = app.Gateway('test')
        with patch.object(media, 'generate', return_value={'data': []}) as generate:
            gateway.dispatch('/v1/videos/generations', {'model':'grok/default', 'prompt':'apple'})
            self.assertEqual(generate.call_args.args[0], 'video')
        self.assertTrue(gateway.slots.acquire(False))
        gateway.slots.release()
