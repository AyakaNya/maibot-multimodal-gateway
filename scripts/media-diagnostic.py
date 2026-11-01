"""Summarize a cached native media tool failure without a new generation."""
import argparse
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from gateway.media_diagnostics import cached_media_failure

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--kind', choices=('image', 'video'), default='image')
args = parser.parse_args()
print(json.dumps(cached_media_failure(root / '.state/grok/sessions', args.kind), indent=2))
