#!/usr/bin/env python3
"""Ad-hoc: API_KEY / X-API-Key for /api/v1."""
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
from unittest import mock

ROOT = %r
sys.path.insert(0, ROOT)
os.environ["NCCM_ADMIN_USER"] = "admin"
os.environ["NCCM_ADMIN_PASS"] = "password123456"
os.environ["NCCM_SESSION_SECRET"] = "testsecret"

from fastapi.testclient import TestClient

def fresh_app():
    import importlib
    import web.api
    import web.main
    importlib.reload(web.api)
    importlib.reload(web.main)
    return TestClient(web.main.app)

with mock.patch("dotenv.load_dotenv", lambda *a, **k: None):
    os.environ.pop("API_KEY", None)
    import importlib
    import web.main
    importlib.reload(web.main)
    c = TestClient(web.main.app)
    r = c.get("/api/v1/inventory")
    assert r.status_code == 500, (r.status_code, r.text[:80])
    print("no API_KEY -> 500 OK")

os.environ["API_KEY"] = "test-api-key-32chars-minimum!!"
c2 = fresh_app()
assert c2.get("/api/v1/inventory").status_code == 401
assert c2.get("/api/v1/inventory", headers={"X-API-Key": "wrong"}).status_code == 401
r = c2.get("/api/v1/inventory", headers={"X-API-Key": "test-api-key-32chars-minimum!!"})
assert r.status_code == 200, (r.status_code, r.text[:200])
assert isinstance(r.json(), list)
print("valid X-API-Key -> 200 OK, rows:", len(r.json()))
assert c2.get("/api/v1/health").json().get("status") == "ok"
print("=== ad-hoc API_KEY verify PASSED ===")
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