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
    monkeypatch.setenv("NCCM_SESSION_SECRET", "switchmap-test-secret")
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
        svc.create_user("viewer1", "password123456", role="viewer")
        from fastapi.testclient import TestClient

        return TestClient(web.main.app)


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert m
    return m.group(1)


def _login(client):
    login = client.get("/login")
    token = _csrf(login.text)
    client.post(
        "/login",
        data={"username": "viewer1", "password": "password123456", "csrf_token": token},
        follow_redirects=False,
    )


def test_switchmap_requires_login(tmp_path, monkeypatch):
    client = _reload_app(tmp_path, monkeypatch)
    r = client.get("/switchmap", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_switchmap_page_loads(tmp_path, monkeypatch):
    client = _reload_app(tmp_path, monkeypatch)
    _login(client)
    r = client.get("/switchmap")
    assert r.status_code == 200
    assert "SwitchMap" in r.text
    assert "/static/switchmap/parse.js" in r.text


def test_vlan_colors_api(tmp_path, monkeypatch):
    client = _reload_app(tmp_path, monkeypatch)
    _login(client)
    r = client.get("/switchmap/api/vlan-colors?site=lab&vlan_ids=1,10")
    assert r.status_code == 200
    data = r.json()
    assert "colors" in data
    assert "1" in data["colors"]
