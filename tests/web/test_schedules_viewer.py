from __future__ import annotations

import importlib
from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest


@pytest.fixture()
def web_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    monkeypatch.setenv("NCCM_AUTH_DB", str(store / "portal_auth.db"))
    monkeypatch.setenv("NCCM_AUDIT_DB", str(store / "audit" / "audit.db"))
    monkeypatch.setenv("NCCM_SESSION_SECRET", "testsecret")
    monkeypatch.setenv("NCCM_NETDRIVER_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("NCCM_ADMIN_USER", raising=False)
    monkeypatch.delenv("NCCM_ADMIN_PASS", raising=False)

    with mock.patch("dotenv.load_dotenv", lambda *a, **k: None):
        import nccm.auth.audit as audit_mod
        import nccm.auth.db as adb
        import nccm.auth.service as svc
        import nccm.config as cfg
        import web.main

        importlib.reload(cfg)
        importlib.reload(adb)
        importlib.reload(audit_mod)
        importlib.reload(svc)
        importlib.reload(web.main)
        from fastapi.testclient import TestClient

        adb.init_auth_db()
        svc.create_user("viewer1", "password123456", role="viewer")
        svc.create_user("ops1", "password123456", role="operator")
        yield TestClient(web.main.app)


def _login(client, username: str) -> None:
    r = client.post(
        "/login",
        data={"username": username, "password": "password123456"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_viewer_schedules_readonly(web_client):
    _login(web_client, "viewer1")
    r = web_client.get("/schedules")
    assert r.status_code == 200
    assert "執行歷史" in r.text
    assert "viewer" in r.text
    assert "新增排程" not in r.text
    assert "立即備份" not in r.text


def test_viewer_cannot_mutate_schedules(web_client):
    _login(web_client, "viewer1")
    assert web_client.post("/schedules/1/run").status_code == 403
    assert web_client.post("/schedules/1/toggle").status_code == 403
    assert web_client.post("/schedules/1/delete").status_code == 403
    assert (
        web_client.post(
            "/schedules/upload",
            data={"name": "x", "interval_days": "1", "username": "u", "password": "p"},
            files={"csv_file": ("t.csv", BytesIO(b"Site,IP,Vendor,Port\n"), "text/csv")},
        ).status_code
        == 403
    )


def test_viewer_can_open_help(web_client):
    _login(web_client, "viewer1")
    r = web_client.get("/help")
    assert r.status_code == 200
    assert "NCCM v3 使用手冊" in r.text


def test_operator_sees_schedule_form(web_client):
    _login(web_client, "ops1")
    r = web_client.get("/schedules")
    assert r.status_code == 200
    assert "新增排程" in r.text
    assert "立即備份" not in r.text  # no schedules yet


def test_help_requires_login(web_client):
    assert web_client.get("/help", follow_redirects=False).status_code == 303
