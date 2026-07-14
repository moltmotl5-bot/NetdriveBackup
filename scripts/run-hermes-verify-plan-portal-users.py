#!/usr/bin/env python3
import os, pathlib, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMPDIR = os.environ.get("TMPDIR") or "/var/folders/py/4zk0t78n2x5bp2br3yfq9l440000gn/T"
INNER = '''
import pathlib
ROOT = %r
p = pathlib.Path(ROOT) / ".hermes/plans/2026-07-14_130000-portal-user-management-db.md"
t = p.read_text(encoding="utf-8")
for n in ("portal_auth.db", "/admin/users", "PLAN ONLY"):
    assert n in t, n
print("plan doc structure: OK")
print("=== ad-hoc plan verify PASSED ===")
''' % ROOT
fd, path = tempfile.mkstemp(suffix=".py", prefix="hermes-verify-", dir=TMPDIR)
with os.fdopen(fd, "w") as f:
    f.write(INNER)
print("created:", path)
proc = subprocess.run([sys.executable, path], cwd=ROOT)
os.unlink(path)
print("cleaned:", path)
sys.exit(proc.returncode)