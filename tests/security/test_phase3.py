from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

import pytest

from nccm.auth.audit import write_audit
from nccm.backup.job_manager import BackupJob, job_accessible
from nccm.security.redaction import redact_text


def _auth_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    monkeypatch.setenv("NCCM_AUTH_DB", str(store / "portal_auth.db"))
    monkeypatch.setenv("NCCM_ADMIN_USER", "envadmin")
    monkeypatch.setenv("NCCM_ADMIN_PASS", "envpassword12345")
    import nccm.auth.db as adb
    import nccm.auth.service as svc

    importlib.reload(adb)
    importlib.reload(svc)
    adb.init_auth_db()
    return svc


def test_break_glass_disabled_when_db_has_users(tmp_path, monkeypatch):
    svc = _auth_env(tmp_path, monkeypatch)
    monkeypatch.delenv("NCCM_BREAK_GLASS", raising=False)
    svc.create_user("dbuser", "dbpassword123456", role="admin")
    assert svc.authenticate("envadmin", "envpassword12345") is None


def test_break_glass_enabled_returns_synthetic_admin(tmp_path, monkeypatch):
    svc = _auth_env(tmp_path, monkeypatch)
    monkeypatch.setenv("NCCM_BREAK_GLASS", "1")
    svc.create_user("dbuser", "dbpassword123456", role="admin")
    user = svc.authenticate("envadmin", "envpassword12345")
    assert user is not None
    assert user.id == 0
    assert user.role == "admin"
    assert user.must_change_password is True


def test_bootstrap_still_works_on_empty_db(tmp_path, monkeypatch):
    svc = _auth_env(tmp_path, monkeypatch)
    monkeypatch.delenv("NCCM_BREAK_GLASS", raising=False)
    user = svc.authenticate("envadmin", "envpassword12345")
    assert user is not None
    assert user.id > 0


def test_login_rate_limit_lockout(monkeypatch):
    import nccm.auth.login_limit as lim

    importlib.reload(lim)
    monkeypatch.setenv("NCCM_LOGIN_MAX_FAILURES", "3")
    monkeypatch.setenv("NCCM_LOGIN_LOCKOUT_SECONDS", "60")
    importlib.reload(lim)

    for _ in range(3):
        lim.record_login_failure(username="alice", ip="10.0.0.1")
    with pytest.raises(lim.LoginRateLimited) as exc:
        lim.check_login_allowed(username="alice", ip="10.0.0.1")
    assert exc.value.retry_after >= 1

    lim.record_login_success(username="alice", ip="10.0.0.1")
    lim.check_login_allowed(username="alice", ip="10.0.0.1")


def test_redact_text_masks_secrets():
    raw = "password=secret123 token=abc authorization: Bearer xyz"
    out = redact_text(raw)
    assert "secret123" not in out
    assert "abc" not in out
    assert "Bearer" not in out or "***" in out


def test_audit_detail_redacted(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    monkeypatch.setenv("NCCM_AUDIT_DB", str(store / "audit.db"))
    import nccm.auth.audit as audit_mod

    importlib.reload(audit_mod)
    audit_mod.write_audit(
        event="test",
        success=True,
        detail="password=hunter2",
    )
    rows = audit_mod.list_audit_events(limit=1)
    assert rows
    assert "hunter2" not in rows[0].detail
    assert "***" in rows[0].detail


def test_draft_password_stored_encrypted(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    import importlib
    import nccm.backup.schedule_draft as draft_mod

    importlib.reload(draft_mod)

    def fake_probe(self, *, ip, port=22, timeout=3.0):
        return {"ok": True, "latency_ms": 1, "msg": ""}

    monkeypatch.setattr("nccm.netdriver.client.NetDriverClient.probe", fake_probe)
    csv_ok = "Site,IP,Vendor,Port\nlab,10.0.0.1,huawei,22\n"
    d = draft_mod.create_draft_from_upload(
        name="t",
        csv_bytes=csv_ok.encode(),
        csv_filename="lab.csv",
        interval_days=1,
        username="u",
        password="plaintext-secret",
    )
    db_path = store / "schedules.db"
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT password FROM schedule_drafts WHERE id = ?", (d.id,)
    ).fetchone()
    conn.close()
    assert row
    stored = str(row[0])
    assert stored.startswith("fernet:")
    assert "plaintext-secret" not in stored


def test_job_accessible_owner_and_admin():
    job = BackupJob(job_id="j1", status="running", owner_uid=42, owner_username="ops")
    assert job_accessible(job, uid=42, role="operator")
    assert not job_accessible(job, uid=99, role="operator")
    assert job_accessible(job, uid=99, role="admin")
    assert not job_accessible(job, uid=0, role="operator")


def test_portal_dockerfile_runs_non_root():
    dockerfile = Path(__file__).resolve().parents[2] / "docker" / "Dockerfile.portal"
    text = dockerfile.read_text(encoding="utf-8")
    assert "USER nccm" in text
    assert "useradd" in text


def test_compose_portal_hardening():
    compose = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    text = compose.read_text(encoding="utf-8")
    assert "container_name: nccm-portal" in text
    assert "no-new-privileges:true" in text
    assert "cap_drop:" in text
    assert "mem_limit: 1g" in text


def test_requirements_pinned():
    req = Path(__file__).resolve().parents[2] / "requirements-v3.txt"
    lines = [ln.strip() for ln in req.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines
    for line in lines:
        assert "==" in line, f"unpinned dependency: {line}"
