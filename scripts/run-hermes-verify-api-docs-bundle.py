#!/usr/bin/env python3
"""Single ad-hoc gate: API token behavior + README/Handbook/.env.example docs."""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

SCRIPTS = [
    "run-hermes-verify-api-key.py",
    "run-hermes-verify-docs-readme-handbook.py",
]

def main() -> int:
    for name in SCRIPTS:
        path = os.path.join(ROOT, "scripts", name)
        print("===", name, "===")
        proc = subprocess.run([PY, path], cwd=ROOT)
        if proc.returncode:
            return proc.returncode
    print("=== ad-hoc api-key + docs bundle PASSED ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())