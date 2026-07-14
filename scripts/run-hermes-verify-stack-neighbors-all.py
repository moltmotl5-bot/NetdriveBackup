#!/usr/bin/env python3
"""Single ad-hoc gate: tempfile hermes-verify-* runs stack resolve unittest + neighbors HTTP smoke."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
TMPDIR = os.environ.get("TMPDIR") or "/var/folders/py/4zk0t78n2x5bp2br3yfq9l440000gn/T"

INNER = r"""
import os
import subprocess
import sys

ROOT = %r
PY = %r
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault("NCCM_ADMIN_USER", "admin")
os.environ.setdefault("NCCM_ADMIN_PASS", "password123456")
os.environ.setdefault("NCCM_SESSION_SECRET", "testsecret")

# 1) Stack device_key -> logical store (mocked unittest)
r1 = subprocess.run(
    [PY, os.path.join(ROOT, "scripts", "hermes-verify-stack-neighbors-resolve.py")],
    cwd=ROOT,
)
if r1.returncode:
    sys.exit(r1.returncode)
print("stack-resolve unittest: OK")

# 2) neighbors_for_device + partial/detail HTTP
from fastapi.testclient import TestClient
from web.main import app
from nccm.inventory.neighbors import neighbor_device_rows, neighbors_for_device

rows, lookup = neighbor_device_rows()
stack = [x for x in rows if x.get("stack_switch") is not None]
if stack:
    dk = stack[0]["device_key"]
    nrows, cdp, _, _ = neighbors_for_device(dk, lookup=lookup)
    print("live stack key:", dk, "cdp:", cdp, "count:", len(nrows))
    if stack[0]["cdp_status"] == "ok" and stack[0]["neighbor_count"] > 0:
        assert cdp == "ok" and len(nrows) == stack[0]["neighbor_count"]
    print("live stack table/detail consistency: OK")
else:
    print("live stack rows: SKIP (no stack in index)")

c = TestClient(app)
c.post("/login", data={"username": "admin", "password": "password123456"}, follow_redirects=False)
resp = c.get("/neighbors/partial/detail", params={"device_key": "MUSEA|10.11.246.213|DS-SW-B2A-1A"})
print("partial/detail status:", resp.status_code)
assert resp.status_code == 200
print("=== ad-hoc hermes-verify stack+neighbors PASSED ===")
""" % (ROOT, PY)

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
    try:
        os.unlink(path)
        print("cleaned:", path)
    except OSError as e:
        print("cleanup note:", e)