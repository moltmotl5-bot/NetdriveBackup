#!/usr/bin/env python3
"""Ad-hoc: README + Handbook mention inventory config download and verify scripts."""
import os
import pathlib
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMPDIR = os.environ.get("TMPDIR") or "/var/folders/py/4zk0t78n2x5bp2br3yfq9l440000gn/T"

INNER = r"""
import pathlib
import sys

ROOT = %r
readme = (pathlib.Path(ROOT) / "README.md").read_text(encoding="utf-8")
handbook = (pathlib.Path(ROOT) / "docs/Handbook.html").read_text(encoding="utf-8")
assert "run-hermes-verify-inventory-config-download.py" in readme
assert "run-hermes-verify-stack-serial.py" in readme
assert "API_KEY" in (pathlib.Path(ROOT) / ".env.example").read_text(encoding="utf-8")
assert "下載" in readme and "config.txt" in readme
assert "/inventory/download/config" in handbook
assert "run-hermes-verify-inventory-config-download.py" in handbook
print("docs readme/handbook inventory download: OK")
print("=== ad-hoc doc verify PASSED ===")
""" % ROOT

fd, path = tempfile.mkstemp(suffix=".py", prefix="hermes-verify-", dir=TMPDIR)
try:
    with os.fdopen(fd, "w") as f:
        f.write(INNER)
    print("created:", path)
    import subprocess

    proc = subprocess.run([sys.executable, path], cwd=ROOT, capture_output=True, text=True)
    print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    if proc.returncode:
        sys.exit(proc.returncode)
finally:
    try:
        os.unlink(path)
        print("cleaned:", path)
    except OSError as e:
        print("cleanup note:", e)