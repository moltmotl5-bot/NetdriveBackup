from __future__ import annotations

import importlib
import os
from pathlib import Path
from unittest import mock

import pytest


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    monkeypatch.setenv("NCCM_AUTH_DB", str(store / "portal_auth.db"))
    monkeypatch.setenv("NCCM_AUDIT_DB", str(store / "audit" / "audit.db"))
    monkeypatch.setenv("NCCM_ADMIN_USER", "admin")
    monkeypatch.setenv("NCCM_ADMIN_PASS", "password123456")
    monkeypatch.setenv("NCCM_SESSION_SECRET", "testsecret")
    monkeypatch.setenv("NCCM_NETDRIVER_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("API_KEY", raising=False)

    with mock.patch("dotenv.load_dotenv", lambda *a, **k: None):
        import nccm.auth.api_tokens as token_mod
        import nccm.auth.audit as audit_mod
        import nccm.auth.db as adb
        import nccm.config as cfg
        import web.api
        import web.main

        importlib.reload(cfg)
        importlib.reload(adb)
        importlib.reload(audit_mod)
        importlib.reload(token_mod)
        importlib.reload(web.api)
        importlib.reload(web.main)
        from fastapi.testclient import TestClient

        yield TestClient(web.main.app), token_mod


def test_inventory_requires_db_token(api_client):
    client, ts = api_client
    assert client.get("/api/v1/inventory").status_code == 500

    from nccm.auth.db import init_auth_db

    init_auth_db()
    _tok, plain = ts.create_token("verify-token", created_by="test")
    assert client.get("/api/v1/inventory").status_code == 401
    r = client.get("/api/v1/inventory", headers={"X-API-Key": plain})
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert isinstance(body, list)


def test_env_api_key_ignored(api_client, monkeypatch: pytest.MonkeyPatch):
    client, ts = api_client
    from nccm.auth.db import init_auth_db

    init_auth_db()
    monkeypatch.setenv("API_KEY", "test-api-key-32chars-minimum!!")
    # reload to pick env — still needs active DB token
    with mock.patch("dotenv.load_dotenv", lambda *a, **k: None):
        import nccm.auth.api_tokens as token_mod
        import web.api
        import web.main

        importlib.reload(token_mod)
        importlib.reload(web.api)
        importlib.reload(web.main)
        from fastapi.testclient import TestClient

        c = TestClient(web.main.app)
    assert c.get(
        "/api/v1/inventory", headers={"X-API-Key": "test-api-key-32chars-minimum!!"}
    ).status_code in (401, 500)
    _, plain2 = token_mod.create_token("second", created_by="test")
    assert (
        c.get("/api/v1/inventory", headers={"X-API-Key": plain2}).status_code == 200
    )


def test_api_health(api_client):
    client, _ = api_client
    assert client.get("/api/v1/health").json().get("status") == "ok"


def test_inventory_item_contract_keys(api_client):
    """Empty inventory still returns list; when non-empty, keys must match contract."""
    client, ts = api_client
    from nccm.auth.db import init_auth_db

    init_auth_db()
    _, plain = ts.create_token("c", created_by="test")
    r = client.get("/api/v1/inventory", headers={"X-API-Key": plain})
    assert r.status_code == 200
    expected = {
        "device_id",
        "site",
        "ip",
        "port",
        "hostname",
        "vendor",
        "sw_version",
        "model_summary",
        "serial_summary",
        "snapshot_count",
        "stack_switch",
        "stack_role",
        "is_config_anchor",
        "cluster_type",
    }
    for item in r.json():
        assert expected <= set(item.keys())
