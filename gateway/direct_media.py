"""DSH-compatible xAI media transport with the gateway's own OAuth session.

Does not read DSH/CLI credentials or invent account permissions.
"""
import base64
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from gateway import app, oauth

API = 'https://api.x.ai/v1'


def call(method, url, token=None, payload=None, limit=24 * 1024 * 1024, timeout=30, transport=None):
    headers = {'Accept': 'application/json'}
    if token is not None:
        headers['Authorization'] = 'Bearer ' + token
    data = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload).encode()
    request = urllib.request.Request(url, data, headers, method=method)
    try:
        with (transport or urllib.request.build_opener(app.NoRedirect)).open(request, timeout=timeout) as response:
            raw = response.read(limit + 1)
            if len(raw) > limit:
                raise app.Failure(502, 'media_size_limit')
            return raw
    except urllib.error.HTTPError as error:
        raise app.Failure(error.code if error.code in (401, 403, 429) else 502, 'media_upstream_' + str(error.code)) from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise app.Failure(502, 'media_upstream_unavailable') from None


def json_call(method, path, payload=None, transport=None):
    token = oauth.access_token()  # Refresh only this gateway's own session.
    try:
        result = json.loads(call(method, API + path, token, payload, transport=transport))
    except ValueError:
        raise app.Failure(502, 'invalid_media_upstream_json') from None
    if not isinstance(result, dict):
        raise app.Failure(502, 'invalid_media_upstream_json')
    return result


def pack(data, kind):
    mime = ('image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else
            'image/jpeg' if data.startswith(b'\xff\xd8\xff') else
            'image/webp' if data.startswith(b'RIFF') and data[8:12] == b'WEBP' else
            'video/mp4' if data[4:8] == b'ftyp' else None)
    if not mime or not mime.startswith(kind + '/'):
        raise app.Failure(502, 'invalid_generated_media')
    if len(data) > (16 if kind == 'image' else 32) * 1024 * 1024:
        raise app.Failure(502, 'media_size_limit')
    return {'b64_json': base64.b64encode(data).decode(), 'media_type': mime,
            'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def reference(value):
    if not isinstance(value, str) or not value.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/webp;base64,')):
        raise app.Failure(400, 'image_reference_requires_base64_data_url')
    try:
        pack(base64.b64decode(value.split(',', 1)[1], validate=True), 'image')
    except (ValueError, app.Failure):
        raise app.Failure(400, 'invalid_reference_image') from None
    return value


def download_url(url):
    if not isinstance(url, str):
        raise app.Failure(502, 'missing_video_url')
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        raise app.Failure(502, 'video_download_host_not_allowed') from None
    # DSH downloads the server-supplied URL without a bearer. Restrict that
    # surface further here; unknown CDN hosts fail closed instead of guessing.
    if parsed.scheme != 'https' or parsed.hostname not in ('vidgen.x.ai', 'imgen.x.ai', 'media.x.ai') or parsed.username or parsed.password or port not in (None, 443):
        raise app.Failure(502, 'video_download_host_not_allowed')
    return url


def generate(kind, body, transport=None, pause=3, max_wait=600):
    expected_model = 'grok-imagine-video-1.5' if kind == 'video' else 'grok-imagine-image-2.0'
    if body.get('model') not in ('grok-oauth/default', 'grok-oauth/' + expected_model):
        raise app.Failure(400, 'invalid_direct_media_model')
    allowed = {'model', 'prompt', 'duration', 'aspect_ratio', 'resolution', 'image'} if kind == 'video' else {'model', 'prompt', 'n', 'size', 'quality', 'images'}
    if set(body) - allowed:
        raise app.Failure(400, 'unsupported_media_fields')
    prompt = body.get('prompt')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
        raise app.Failure(400, 'invalid_prompt')
    payload = {'model': expected_model, 'prompt': prompt}
    if kind in ('image', 'edit'):
        if type(body.get('n', 1)) is not int or body.get('n', 1) != 1:
            raise app.Failure(400, 'only_one_image_supported')
        ratios = {'auto': 'auto', '1024x1024': '1:1', '1536x1024': '3:2', '1024x1536': '2:3'}
        if not isinstance(body.get('size', 'auto'), str) or body.get('size', 'auto') not in ratios:
            raise app.Failure(400, 'invalid_size')
        payload.update(response_format='b64_json', aspect_ratio=ratios[body.get('size', 'auto')])
        if 'quality' in body:
            if body['quality'] not in ('low', 'medium'):
                raise app.Failure(400, 'invalid_quality')
            payload['quality'] = body['quality']
        if kind == 'edit':
            refs = body.get('images')
            if not isinstance(refs, list) or not 1 <= len(refs) <= 3:
                raise app.Failure(400, 'one_to_three_reference_images_required')
            refs = [reference(value) for value in refs]
            if len(refs) == 1:
                payload['image'] = {'type': 'image_url', 'url': refs[0]}
            else:
                payload['images'] = [{'type': 'image_url', 'url': value} for value in refs]
        elif 'images' in body:
            raise app.Failure(400, 'use_image_edits_route')
        result = json_call('POST', '/images/edits' if kind == 'edit' else '/images/generations', payload, transport)
        try:
            data = base64.b64decode(result['data'][0]['b64_json'], validate=True)
        except (KeyError, IndexError, TypeError, ValueError):
            raise app.Failure(502, 'missing_image_data') from None
        output = pack(data, 'image')
    else:
        duration = body.get('duration', 6)
        if type(duration) is not int or not 1 <= duration <= 15:
            raise app.Failure(400, 'invalid_duration')
        aspect = body.get('aspect_ratio', '16:9')
        resolution = body.get('resolution', '480p')
        if aspect not in ('16:9', '9:16', '1:1', '4:3', '3:4', '3:2', '2:3') or resolution not in ('480p', '720p', '1080p'):
            raise app.Failure(400, 'invalid_video_options')
        payload.update(duration=duration, aspect_ratio=aspect, resolution=resolution)
        if 'image' in body:
            payload['image'] = {'url': reference(body['image'])}
        start = json_call('POST', '/videos/generations', payload, transport)
        request_id = start.get('request_id')
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 500:
            raise app.Failure(502, 'missing_video_request_id')
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            if pause:
                time.sleep(min(pause, max(0, deadline - time.monotonic())))
            if time.monotonic() >= deadline:
                raise app.Failure(504, 'video_generation_timeout')
            result = json_call('GET', '/videos/' + urllib.parse.quote(request_id, safe=''), transport=transport)
            status = result.get('status')
            if status == 'done':
                video = result.get('video')
                url = download_url(video.get('url') if isinstance(video, dict) else None)
                # Intentionally no OAuth bearer, no redirects, no raw signed URL in response.
                output = pack(call('GET', url, limit=32 * 1024 * 1024, transport=transport), 'video')
                break
            if status in ('failed', 'expired'):
                raise app.Failure(502, 'video_generation_' + status)
            if status != 'pending':
                raise app.Failure(502, 'unknown_video_status')
        else:
            raise app.Failure(504, 'video_generation_timeout')
    return {'created': int(time.time()), 'model': 'grok-oauth/' + expected_model,
            'authentication': 'gateway_approved_oauth', 'account_entitlement': 'request_succeeded', 'data': [output]}
