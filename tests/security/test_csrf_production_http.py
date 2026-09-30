from __future__ import annotations

import importlib
import re
from pathlib import Path
from unittest import mock

import pytest
from starlette.testclient import TestClient


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **extra_env: str) -> TestClient:
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    monkeypatch.setenv("NCCM_AUTH_DB", str(store / "portal_auth.db"))
    monkeypatch.setenv("NCCM_SESSION_SECRET", "csrf-test-secret")
    monkeypatch.setenv("NCCM_NETDRIVER_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("NCCM_ADMIN_USER", raising=False)
    monkeypatch.delenv("NCCM_ADMIN_PASS", raising=False)
    for key in ("NCCM_ENV", "NCCM_HTTPS"):
        monkeypatch.delenv(key, raising=False)
    for key, val in extra_env.items():
        monkeypatch.setenv(key, val)
    with mock.patch("dotenv.load_dotenv", lambda *a, **k: None):
        import nccm.auth.db as adb
        import nccm.auth.service as svc
        import nccm.config as cfg
        import web.main

        importlib.reload(cfg)
        importlib.reload(adb)
        importlib.reload(svc)
        importlib.reload(web.main)
        adb.init_auth_db()
        svc.create_user("ops1", "password123456", role="operator")
        return TestClient(web.main.app)


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert m
    return m.group(1)


def test_login_csrf_works_on_http_with_production_env(tmp_path, monkeypatch):
    """NCCM_ENV=production must not break HTTP login (no spurious Secure cookies)."""
    client = _client(tmp_path, monkeypatch, NCCM_ENV="production")
    login = client.get("/login")
    token = _csrf(login.text)
    r = client.post(
        "/login",
        data={"username": "ops1", "password": "password123456", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text


def test_https_flag_enables_secure_cookies(tmp_path, monkeypatch):
    from web.security import https_only_cookies

    monkeypatch.setenv("NCCM_HTTPS", "1")
    monkeypatch.setenv("NCCM_ENV", "production")
    assert https_only_cookies() is True
