#!/usr/bin/env python3
"""Ad-hoc: /api/v1 uses DB API tokens only (replaces legacy API_KEY env test)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
proc = subprocess.run(
    [sys.executable, str(ROOT / "scripts/run-hermes-verify-api-tokens.py")],
    cwd=ROOT,
)
sys.exit(proc.returncode)