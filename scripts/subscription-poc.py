"""One real local subscription text request; no API-key fallback."""
import argparse
import json
from pathlib import Path
import urllib.error
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('--provider', choices=['chatgpt', 'grok', 'gemini'], required=True)
parser.add_argument('--model', default='default', help='default uses runtime selection; or an account-visible model ID')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
key = (root / '.state/gateway.key').read_text().strip()
body = {'model': args.provider + '/' + args.model, 'messages': [{'role': 'user', 'content': '只用一句話回覆：訂閱文字路由測試成功。'}]}
req = urllib.request.Request('http://127.0.0.1:8790/v1/chat/completions', json.dumps(body).encode(),
    {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
try:
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=180) as response:
        result = json.load(response)
        print(result['choices'][0]['message']['content'])
except urllib.error.HTTPError as error:
    detail = json.load(error).get('error', {}).get('code', 'unknown')
    raise SystemExit(f'HTTP {error.code}: {detail}. No API fallback attempted.')
except urllib.error.URLError:
    raise SystemExit('Gateway unavailable. Start python3 -m gateway.app serve first.')
