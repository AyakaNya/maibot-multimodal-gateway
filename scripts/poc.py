"""Run from project root: python3 scripts/poc.py --model xai/grok-imagine-image-2.0"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import urllib.request
import urllib.error

parser = argparse.ArgumentParser()
parser.add_argument('--model', default='openai/gpt-image-1')
parser.add_argument('--port', type=int, default=8790)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
key = (root / '.state/gateway.key').read_text().strip()
request = urllib.request.Request(f'http://127.0.0.1:{args.port}/v1/images/generations',
    json.dumps({'model': args.model, 'prompt': 'A red apple on a plain white table', 'n': 1}).encode(),
    {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
try:
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=150) as response:
        result = json.load(response)
except urllib.error.HTTPError as error:
    raise SystemExit(f'Gateway HTTP {error.code}; check provider configuration/entitlement. No fallback attempted.')
image = base64.b64decode(result['data'][0]['b64_json'], validate=True)
kind = 'png' if image.startswith(b'\x89PNG\r\n\x1a\n') else 'jpg' if image.startswith(b'\xff\xd8\xff') else 'webp' if image.startswith(b'RIFF') and image[8:12] == b'WEBP' else None
if kind is None:
    raise SystemExit('Upstream did not return recognized image bytes')
out = root / 'artifacts'
out.mkdir(mode=0o700, exist_ok=True)
path = out / ('poc.' + kind)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, 'wb') as file:
    file.write(image)
print(json.dumps({'model': args.model, 'path': str(path), 'bytes': len(image), 'sha256': hashlib.sha256(image).hexdigest()}))
