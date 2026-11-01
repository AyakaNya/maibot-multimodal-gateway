"""Grok PKCE with an operator's approved OAuth client, never a borrowed CLI id."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from gateway.app import Failure, NoRedirect, read_secret, save_secret


def checked(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'auth.x.ai' or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise RuntimeError('OAuth endpoints must be HTTPS on auth.x.ai')
    return url


def fetch_json(url, form=None):
    data = None if form is None else urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(checked(url), data, {'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as response:
            return json.loads(response.read(1024 * 1024))
    except Exception:
        raise Failure(503, 'oauth_request_failed_reauthorize_or_check_entitlement') from None


def endpoints():
    doc = fetch_json('https://auth.x.ai/.well-known/openid-configuration')
    return checked(doc['authorization_endpoint']), checked(doc['token_endpoint'])


def login():
    client = os.environ.get('GROK_APPROVED_CLIENT_ID')
    redirect = os.environ.get('GROK_APPROVED_REDIRECT_URI')
    if not client or not redirect:
        raise SystemExit('Set your approved GROK_APPROVED_CLIENT_ID and GROK_APPROVED_REDIRECT_URI. CLI client IDs are not supplied.')
    uri = urllib.parse.urlsplit(redirect)
    if uri.scheme != 'http' or uri.hostname != '127.0.0.1' or not uri.port or uri.query or uri.fragment or uri.username:
        raise SystemExit('Approved redirect must be http://127.0.0.1:PORT/callback')
    authorize, token = endpoints()
    verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    result = {}
    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            request = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(request.query)
            valid = request.path == uri.path and hmac.compare_digest(query.get('state', [''])[0], state)
            code = query.get('code', [''])[0]
            if valid and code:
                result['code'] = code
            self.send_response(200 if valid and code else 400)
            self.end_headers()
            self.wfile.write(b'Authorization received. Return to terminal.' if result else b'Invalid callback.')
    with HTTPServer(('127.0.0.1', uri.port), Callback) as callback:
        callback.timeout = 1
        params = {'response_type': 'code', 'client_id': client, 'redirect_uri': redirect,
                  'scope': 'openid profile email offline_access grok-cli:access api:access',
                  'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256'}
        print('Open locally in a browser (expires in 180 seconds):\n' + authorize + '?' + urllib.parse.urlencode(params))
        deadline = time.monotonic() + 180
        while not result and time.monotonic() < deadline:
            callback.handle_request()
    if not result:
        raise SystemExit('Authorization timed out; no credential saved.')
    tokens = fetch_json(token, {'grant_type': 'authorization_code', 'client_id': client,
        'redirect_uri': redirect, 'code': result['code'], 'code_verifier': verifier,
        'code_challenge': challenge, 'code_challenge_method': 'S256'})
    persist(tokens, client, token)
    print('Stored Grok OAuth credential. Inference entitlement remains unverified.')


def persist(tokens, client, endpoint, previous=None):
    if not isinstance(tokens.get('access_token'), str) or not tokens['access_token'] or not isinstance(tokens.get('expires_in'), (int, float)) or tokens['expires_in'] <= 0:
        raise Failure(503, 'invalid_oauth_response')
    record = {'access_token': tokens['access_token'], 'refresh_token': tokens.get('refresh_token', previous),
              'expires_at': time.time() + tokens['expires_in'], 'client_id': client, 'token_endpoint': checked(endpoint)}
    save_secret('grok.oauth.json', json.dumps(record))
    return record


def access_token():
    raw = read_secret('grok.oauth.json')
    if not raw:
        raise Failure(503, 'grok_oauth_not_configured')
    record = json.loads(raw)
    if record['expires_at'] < time.time() + 60:
        if not record.get('refresh_token'):
            raise Failure(401, 'grok_reauthorization_required')
        tokens = fetch_json(checked(record['token_endpoint']), {'grant_type': 'refresh_token',
            'client_id': record['client_id'], 'refresh_token': record['refresh_token']})
        record = persist(tokens, record['client_id'], record['token_endpoint'], record['refresh_token'])
    return record['access_token']
