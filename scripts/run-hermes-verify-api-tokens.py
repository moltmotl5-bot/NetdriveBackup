#!/usr/bin/env python3
"""Ad-hoc: DB api_tokens + env API_KEY dual-track for /api/v1."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMPDIR = os.environ.get("TMPDIR") or "/var/folders/py/4zk0t78n2x5bp2br3yfq9l440000gn/T"

INNER = r"""
import os
import sys
from pathlib import Path
from unittest import mock

ROOT = %r
work = Path(%r)
os.environ["NCCM_STORE_DIR"] = str(work / "store")
os.environ["NCCM_AUTH_DB"] = str(work / "store" / "portal_auth.db")
os.environ["NCCM_ADMIN_USER"] = "admin"
os.environ["NCCM_ADMIN_PASS"] = "password123456"
os.environ["NCCM_SESSION_SECRET"] = "testsecret"
os.environ["NCCM_NETDRIVER_URL"] = "http://127.0.0.1:9"
os.environ["NCCM_API_IMPORT_ENV"] = "0"
os.environ.pop("API_KEY", None)

sys.path.insert(0, ROOT)

def fresh_client():
    import importlib
    import nccm.auth.api_tokens as token_mod
    import web.api
    import web.main
    importlib.reload(token_mod)
    importlib.reload(web.api)
    importlib.reload(web.main)
    from fastapi.testclient import TestClient
    return TestClient(web.main.app)

with mock.patch("dotenv.load_dotenv", lambda *a, **k: None):
    c = fresh_client()
    assert c.get("/api/v1/inventory").status_code == 500
    print("no token source -> 500 OK")

    from nccm.auth.db import init_auth_db
    from nccm.auth import api_tokens as ts

    init_auth_db()
    tok, plain = ts.create_token("verify-token", created_by="test")
    assert plain.startswith("nccm_")
    c2 = fresh_client()
    assert c2.get("/api/v1/inventory").status_code == 401
    r = c2.get("/api/v1/inventory", headers={"X-API-Key": plain})
    assert r.status_code == 200, (r.status_code, r.text[:200])
    print("DB token -> 200 OK")

    ts.set_token_active(tok.id, False)
    assert ts.active_token_count() == 0
    assert ts.authenticate_api_key(plain) is None
    st = c2.get("/api/v1/inventory", headers={"X-API-Key": plain}).status_code
    assert st in (401, 500), st
    print("deactivated token ->", st, "OK")

    os.environ["API_KEY"] = "test-api-key-32chars-minimum!!"
    c4 = fresh_client()
    r4 = c4.get("/api/v1/inventory", headers={"X-API-Key": "test-api-key-32chars-minimum!!"})
    assert r4.status_code == 200, (r4.status_code, r4.text[:120])
    print("env API_KEY dual-track -> 200 OK")

    assert c4.get("/api/v1/health").json().get("status") == "ok"
    print("=== ad-hoc api-tokens verify PASSED ===")
""" % (ROOT, "WORKPLACE")

work = tempfile.mkdtemp(prefix="hermes-verify-", dir=TMPDIR)
inner = INNER.replace("WORKPLACE", work)
fd, path = tempfile.mkstemp(suffix=".py", prefix="hermes-verify-", dir=TMPDIR)
child_env = os.environ.copy()
child_env.pop("API_KEY", None)
try:
    with os.fdopen(fd, "w") as f:
        f.write(inner)
    print("created:", path)
    proc = subprocess.run(
        [sys.executable, path], cwd=ROOT, capture_output=True, text=True, env=child_env
    )
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