from __future__ import annotations

import importlib
import re
from pathlib import Path
from unittest import mock

import pytest


def _reload_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    monkeypatch.setenv("NCCM_AUTH_DB", str(store / "portal_auth.db"))
    monkeypatch.setenv("NCCM_SESSION_SECRET", "csrf-test-secret")
    monkeypatch.setenv("NCCM_NETDRIVER_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("NCCM_ADMIN_USER", raising=False)
    monkeypatch.delenv("NCCM_ADMIN_PASS", raising=False)
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
        from fastapi.testclient import TestClient

        return TestClient(web.main.app)


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert m
    return m.group(1)


def test_post_without_csrf_rejected(tmp_path, monkeypatch):
    client = _reload_app(tmp_path, monkeypatch)
    login = client.get("/login")
    token = _csrf(login.text)
    client.post(
        "/login",
        data={"username": "ops1", "password": "password123456", "csrf_token": token},
        follow_redirects=False,
    )
    r = client.post("/inventory/rebuild")
    assert r.status_code == 403
    assert "CSRF" in r.text


def test_post_with_csrf_allowed(tmp_path, monkeypatch):
    client = _reload_app(tmp_path, monkeypatch)
    login = client.get("/login")
    token = _csrf(login.text)
    client.post(
        "/login",
        data={"username": "ops1", "password": "password123456", "csrf_token": token},
        follow_redirects=False,
    )
    page = client.get("/inventory")
    token = _csrf(page.text)
    r = client.post("/inventory/rebuild", data={"csrf_token": token}, follow_redirects=False)
    assert r.status_code == 303


def test_security_headers_present(tmp_path, monkeypatch):
    client = _reload_app(tmp_path, monkeypatch)
    r = client.get("/login")
    assert "content-security-policy" in {k.lower() for k in r.headers}
    assert "default-src 'self'" in r.headers.get("content-security-policy", "")


def test_no_inline_onclick_in_inventory_partial(tmp_path, monkeypatch):
    client = _reload_app(tmp_path, monkeypatch)
    login = client.get("/login")
    token = _csrf(login.text)
    client.post(
        "/login",
        data={"username": "ops1", "password": "password123456", "csrf_token": token},
    )
    r = client.get("/inventory/partial/table")
    assert "onclick=" not in r.text
