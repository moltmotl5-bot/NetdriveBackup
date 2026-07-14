#!/usr/bin/env python3
"""Ad-hoc: portal user DB auth, roles, admin page access."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMPDIR = os.environ.get("TMPDIR") or "/var/folders/py/4zk0t78n2x5bp2br3yfq9l440000gn/T"

INNER = r"""
import os
import sys
from pathlib import Path

ROOT = %r
work = Path(%r)
os.environ["NCCM_STORE_DIR"] = str(work / "store")
os.environ["NCCM_AUTH_DB"] = str(work / "store" / "portal_auth.db")
os.environ["NCCM_ADMIN_USER"] = "bootadmin"
os.environ["NCCM_ADMIN_PASS"] = "BootstrapPass12!"
os.environ["NCCM_SESSION_SECRET"] = "test-secret-fixed-for-verify"
os.environ["NCCM_NETDRIVER_URL"] = "http://127.0.0.1:9"

sys.path.insert(0, ROOT)

from nccm.auth import passwords, service
from nccm.auth.db import init_auth_db

assert passwords.verify_password("wrong", passwords.hash_password("BootstrapPass12!")) is False
h = passwords.hash_password("BootstrapPass12!")
assert passwords.verify_password("BootstrapPass12!", h)

init_auth_db()
assert service.user_count() == 0
u = service.authenticate("bootadmin", "BootstrapPass12!")
assert u and u.role == "admin" and u.id > 0
assert service.user_count() == 1

service.create_user("viewer1", "ViewerPass12345", role="viewer")
v = service.authenticate("viewer1", "ViewerPass12345")
assert v and v.role == "viewer"

from fastapi.testclient import TestClient
from web.main import app

client = TestClient(app)
r = client.post(
    "/login",
    data={"username": "bootadmin", "password": "BootstrapPass12!"},
    follow_redirects=False,
)
assert r.status_code == 303, r.status_code
r = client.get("/admin/users")
assert r.status_code == 200, r.status_code
assert "使用者管理" in r.text

client.post("/logout", follow_redirects=False)
r = client.post(
    "/login",
    data={"username": "viewer1", "password": "ViewerPass12345"},
    follow_redirects=False,
)
assert r.status_code == 303
assert r.headers.get("location", "").endswith("/inventory")
r = client.get("/admin/users")
assert r.status_code == 403
r = client.get("/backup")
assert r.status_code == 403
r = client.get("/inventory")
assert r.status_code == 200

print("portal users auth + rbac: OK")
print("=== ad-hoc portal-users verify PASSED ===")
""" % (ROOT, "WORKPLACE")

work = tempfile.mkdtemp(prefix="hermes-verify-", dir=TMPDIR)
inner = INNER.replace("WORKPLACE", work)
fd, path = tempfile.mkstemp(suffix=".py", prefix="hermes-verify-", dir=TMPDIR)
try:
    with os.fdopen(fd, "w") as f:
        f.write(inner)
    print("created:", path)
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
    shutil.rmtree(work, ignore_errors=True)
    print("cleaned workdir:", work)