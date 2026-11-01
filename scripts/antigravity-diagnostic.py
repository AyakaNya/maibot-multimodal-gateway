"""Inspect shared agy extension metadata offline; never run CLI tools or generate."""
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from gateway.antigravity_preflight import shared_extensions_report

print(json.dumps(shared_extensions_report(), indent=2))
