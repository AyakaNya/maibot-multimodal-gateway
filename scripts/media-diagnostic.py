"""Summarize the most recent cached image tool failure without a new generation."""
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from gateway.media_diagnostics import cached_image_failure

print(json.dumps(cached_image_failure(root / '.state/grok/sessions'), indent=2))
