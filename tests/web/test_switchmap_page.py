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
    assert "SwitchMap — NCCM v3" in r.text
    assert "/static/switchmap/parse.js" in r.text
    assert "/static/nccm.css" in r.text


def test_switchmap_page_with_cisco_inventory_rows(tmp_path, monkeypatch):
    """Regression: neighbor_device_rows returns dicts; attribute access caused HTTP 500."""
    client = _reload_app(tmp_path, monkeypatch)
    _login(client)
    cisco_row = {
        "device_key": "lab|10.0.0.1|sw1|22",
        "device_id": "lab::10.0.0.1::22::sw1",
        "site": "lab",
        "ip": "10.0.0.1",
        "port": 22,
        "hostname": "sw1",
        "vendor": "cisco",
        "sw_version": "",
        "model_summary": "",
        "serial_summary": "",
        "stack_switch": False,
        "stack_role": "",
        "cluster_type": "",
        "is_config_anchor": True,
        "neighbor_count": 0,
        "cdp_status": "",
        "lldp_status": "",
    }
    with mock.patch(
        "nccm.inventory.neighbors.neighbor_device_rows",
        return_value=([cisco_row], {}),
    ):
        r = client.get("/switchmap")
    assert r.status_code == 200
    assert "sw1" in r.text


def test_vlan_colors_api(tmp_path, monkeypatch):
    client = _reload_app(tmp_path, monkeypatch)
    _login(client)
    r = client.get("/switchmap/api/vlan-colors?site=lab&vlan_ids=1,10")
    assert r.status_code == 200
    data = r.json()
    assert "colors" in data
    assert "1" in data["colors"]
    from nccm.switchmap import vlan_colors as vc

    for entry in data["colors"].values():
        assert vc.pair_meets_wcag_aa(entry["fill"], entry["text"])
