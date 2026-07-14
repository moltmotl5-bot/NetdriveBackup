#!/usr/bin/env python3
"""One-shot ad-hoc verify: writes hermes-verify-* under system temp, runs, deletes."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
TMPDIR = os.environ.get("TMPDIR") or "/var/folders/py/4zk0t78n2x5bp2br3yfq9l440000gn/T"

INNER = r"""
import os, sys
ROOT = %r
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault("NCCM_ADMIN_USER", "admin")
os.environ.setdefault("NCCM_ADMIN_PASS", "password123456")
os.environ.setdefault("NCCM_SESSION_SECRET", "testsecret")
from nccm.inventory.neighbors import neighbors_for_device
neighbors_for_device("MUSEA|10.11.246.213|DS-SW-B2A-1A", lookup={})
print("neighbors_for_device: OK (no NameError)")
from fastapi.testclient import TestClient
from web.main import app
c = TestClient(app)
c.post("/login", data={"username": "admin", "password": "password123456"}, follow_redirects=False)
r = c.get("/neighbors/partial/detail", params={"device_key": "MUSEA|10.11.246.213|DS-SW-B2A-1A"})
print("partial/detail status:", r.status_code)
assert r.status_code == 200, r.text[:400]
print("=== ad-hoc hermes-verify PASSED ===")
""" % ROOT

fd, path = tempfile.mkstemp(suffix=".py", prefix="hermes-verify-", dir=TMPDIR)
try:
    with os.fdopen(fd, "w") as f:
        f.write(INNER)
    print("created:", path)
    proc = subprocess.run([PY, path], cwd=ROOT, capture_output=True, text=True)
    print(proc.stdout, end="")
    if proc.stderr:
        print("stderr:", proc.stderr, file=sys.stderr)
    if proc.returncode != 0:
        sys.exit(proc.returncode)
finally:
    try:
        os.unlink(path)
        print("cleaned:", path)
    except OSError as e:
        print("cleanup note:", e)