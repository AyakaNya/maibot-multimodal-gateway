"""Real Grok CLI OAuth media request through the localhost gateway."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('--provider', choices=['grok', 'chatgpt', 'gemini'], default='grok')
parser.add_argument('--kind', choices=['image', 'edit', 'video'], required=True)
parser.add_argument('--backend', choices=['cli', 'oauth'], default='cli')
parser.add_argument('--reference-image', type=Path, help='Local PNG/JPEG/WebP explicitly supplied for editing or image-to-video')
parser.add_argument('--prompt', default='A red apple on a white table, gentle camera movement')
args = parser.parse_args()
if args.provider != 'grok' and (args.backend != 'cli' or args.kind != 'image' or args.reference_image):
    parser.error('ChatGPT/Gemini currently support --backend cli --kind image only')
root = Path(__file__).resolve().parents[1]
key = (root / '.state/gateway.key').read_text().strip()
route = {'image':'/v1/images/generations','edit':'/v1/images/edits','video':'/v1/videos/generations'}[args.kind]
body = {'model': ('grok-oauth/default' if args.backend == 'oauth' else args.provider + '/default'), 'prompt': args.prompt}
if args.kind == 'edit' and (args.backend != 'oauth' or args.reference_image is None):
    parser.error('Editing requires --backend oauth --reference-image PATH')
if args.reference_image:
    if args.backend != 'oauth' or args.kind == 'image':
        parser.error('Reference images require --backend oauth and --kind edit|video')
    raw = args.reference_image.read_bytes()
    if len(raw) > 700 * 1024:
        parser.error('Reference image must be <=700 KiB for the current 1 MiB JSON request limit')
    mime = 'image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg' if raw.startswith(b'\xff\xd8\xff') else 'image/webp' if raw.startswith(b'RIFF') and raw[8:12] == b'WEBP' else None
    if not mime:
        parser.error('Reference must be PNG/JPEG/WebP')
    ref = 'data:' + mime + ';base64,' + base64.b64encode(raw).decode()
    body.update({'images':[ref]} if args.kind == 'edit' else {'image':ref})
if args.kind == 'video':
    body['duration'] = 6
req = urllib.request.Request('http://127.0.0.1:8790' + route, json.dumps(body).encode(),
    {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
try:
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=630) as response:
        result = json.load(response)['data'][0]
except urllib.error.HTTPError as error:
    code = json.load(error).get('error', {}).get('code', 'unknown')
    if args.provider != 'grok':
        print('Diagnostic: cat .state/subscription-image-diagnostic.json (redacted fields only).')
    elif args.backend == 'cli' and code.startswith('media_'):
        print('Diagnostic: cat .state/media-diagnostic.json (redacted fields only). Also check grok version.')
        print(f'Offline tool failure details: python3 scripts/media-diagnostic.py --kind {args.kind}')
    raise SystemExit(f'HTTP {error.code}: {code}. No API-key fallback attempted.')
except urllib.error.URLError:
    raise SystemExit('Start the gateway on port 8790 first.')
data = base64.b64decode(result['b64_json'], validate=True)
if hashlib.sha256(data).hexdigest() != result['sha256']:
    raise SystemExit('Media checksum mismatch.')
ext = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'video/mp4': 'mp4'}[result['media_type']]
folder = root / 'artifacts'
if folder.is_symlink():
    raise SystemExit('Unsafe artifact directory.')
folder.mkdir(mode=0o700, exist_ok=True)
path = folder / (args.provider + '-poc.' + ext)
fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, 'wb') as output:
    output.write(data)
print(json.dumps({'path': str(path), 'bytes': len(data), 'sha256': result['sha256']}))
