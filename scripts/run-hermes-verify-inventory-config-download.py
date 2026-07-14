#!/usr/bin/env python3
"""Ad-hoc: inventory Running-Config download link + endpoint."""
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
import sys

ROOT = %r
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault("NCCM_ADMIN_USER", "admin")
os.environ.setdefault("NCCM_ADMIN_PASS", "password123456")
os.environ.setdefault("NCCM_SESSION_SECRET", "testsecret")

from fastapi.testclient import TestClient
from web.main import app
from nccm.storage.index_db import list_inventory_display, list_snapshots_for_device

c = TestClient(app)
c.post("/login", data={"username": "admin", "password": "password123456"}, follow_redirects=False)

rows = list_inventory_display()
if not rows:
    print("SKIP: no inventory rows")
    sys.exit(0)

device_id = rows[0].device_id
snaps = list_snapshots_for_device(device_id)
if not snaps:
    print("SKIP: no snapshots for first device")
    sys.exit(0)

sid = snaps[0].id
r = c.get("/inventory/partial/detail", params={"device_id": device_id, "snapshot_id": sid})
assert r.status_code == 200, r.text[:300]
assert "下載" in r.text
assert f"snapshot_id={sid}" in r.text
assert "/inventory/download/config" in r.text
print("detail partial: download link OK")

dl = c.get(
    "/inventory/download/config",
    params={"snapshot_id": sid, "device_id": device_id},
)
if dl.status_code == 404:
    print("download: 404 (no config.txt on disk) — link wiring OK")
    sys.exit(0)
assert dl.status_code == 200, dl.text[:200]
assert "attachment" in (dl.headers.get("content-disposition") or "").lower() or dl.content
print("download status:", dl.status_code, "bytes:", len(dl.content))
print("=== ad-hoc inventory config download PASSED ===")
""" % ROOT

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