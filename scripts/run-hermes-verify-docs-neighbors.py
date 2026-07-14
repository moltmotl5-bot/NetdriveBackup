#!/usr/bin/env python3
"""Ad-hoc: verify README/Handbook mention neighbor verify scripts (uses system temp)."""
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
TMPDIR = os.environ.get("TMPDIR") or "/var/folders/py/4zk0t78n2x5bp2br3yfq9l440000gn/T"
NEEDLE = "hermes-verify-neighbors-detail.py"

INNER = """
import pathlib
ROOT = %r
readme = (pathlib.Path(ROOT) / "README.md").read_text(encoding="utf-8")
handbook = (pathlib.Path(ROOT) / "docs/Handbook.html").read_text(encoding="utf-8")
needle = %r
assert needle in readme, "README missing neighbors verify script"
assert needle in handbook, "Handbook missing neighbors verify script"
assert "run-hermes-verify-temp-neighbors.py" in readme
print("docs cross-check: OK")
print("=== ad-hoc doc verify PASSED ===")
""" % (ROOT, NEEDLE)

fd, path = tempfile.mkstemp(suffix=".py", prefix="hermes-verify-", dir=TMPDIR)
try:
    with os.fdopen(fd, "w") as f:
        f.write(INNER)
    print("created:", path)
    proc = subprocess.run([PY, path], cwd=ROOT, capture_output=True, text=True)
    print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    if proc.returncode:
        sys.exit(proc.returncode)
finally:
    os.unlink(path)
    print("cleaned:", path)