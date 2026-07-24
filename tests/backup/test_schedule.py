from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet


@pytest.fixture()
def sched_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    monkeypatch.delenv("NCCM_SECRETS_KEY", raising=False)
    monkeypatch.delenv("NCCM_SECRETS_KEY_FILE", raising=False)
    import importlib
    import nccm.backup.schedule as sch
    import nccm.backup.secrets as secrets

    importlib.reload(secrets)
    importlib.reload(sch)
    yield sch
    importlib.reload(secrets)
    importlib.reload(sch)


@pytest.fixture()
def sched_env_with_key(sched_env, monkeypatch: pytest.MonkeyPatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("NCCM_SECRETS_KEY", key)
    import importlib
    import nccm.backup.secrets as secrets
    import nccm.backup.schedule as sch

    importlib.reload(secrets)
    importlib.reload(sch)
    yield sch


CSV_OK = """Site,IP,Vendor,Port
lab,10.0.0.1,huawei,22
lab,10.0.0.2,cisco,22
"""


def test_mock_run_csv(sched_env):
    sch = sched_env
    r = sch.mock_run_csv(CSV_OK)
    assert r["mode"] == "dry-mock"
    assert r["device_count"] == 2
    assert r["devices"][0]["ip"] == "10.0.0.1"


def test_create_and_run_schedule(sched_env):
    sch = sched_env
    result = sch.create_schedule("lab", CSV_OK, every_minutes=30)
    s = result.schedule
    assert s.id > 0
    assert s.mode == sch.MODE_DRY_MOCK
    assert s.password_set is False
    assert result.key_created is False
    r = sch.run_schedule(s.id)
    assert r["ok"] is True
    assert r["device_count"] == 2
    again = sch.get_schedule(s.id)
    assert again and again.last_run_at
    assert "mock" in (again.last_result or "")


def test_bad_csv_raises(sched_env):
    sch = sched_env
    with pytest.raises(ValueError):
        sch.mock_run_csv("noheader\n1,2,3")


def test_live_auto_init_master_key_on_first_create(sched_env):
    sch = sched_env
    from nccm.backup.secrets import secrets_configured, store_master_key_path

    assert secrets_configured() is False
    result = sch.create_schedule(
        "live",
        CSV_OK,
        mode=sch.MODE_LIVE,
        username="admin",
        password="secret",
    )
    assert result.key_created is True
    assert result.key_source == "store"
    assert secrets_configured() is True
    assert store_master_key_path().is_file()
    s = result.schedule
    assert s.mode == sch.MODE_LIVE
    assert s.password_set is True


def test_live_auto_init_idempotent(sched_env):
    sch = sched_env
    first = sch.create_schedule(
        "live1",
        CSV_OK,
        mode=sch.MODE_LIVE,
        username="admin",
        password="secret",
    )
    assert first.key_created is True
    second = sch.create_schedule(
        "live2",
        CSV_OK,
        mode=sch.MODE_LIVE,
        username="admin2",
        password="secret2",
    )
    assert second.key_created is False


def test_create_live_schedule_encrypted(sched_env_with_key):
    sch = sched_env_with_key
    result = sch.create_schedule(
        "live-lab",
        CSV_OK,
        mode=sch.MODE_LIVE,
        username="netops",
        password="ssh-pass",
        enable_password="enable1",
        created_by="admin",
    )
    s = result.schedule
    assert s.mode == sch.MODE_LIVE
    assert s.username == "netops"
    assert s.password_set is True
    assert s.enable_password_set is True
    assert result.key_created is False

    with sqlite3.connect(str(sch.schedules_db_path())) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT password_enc, enable_password_enc FROM schedules WHERE id = ?",
            (s.id,),
        ).fetchone()
        assert row
        assert "ssh-pass" not in str(row["password_enc"])
        assert "enable1" not in str(row["enable_password_enc"])

    creds = sch.resolve_schedule_credentials(s.id)
    assert creds.username == "netops"
    assert creds.password == "ssh-pass"
    assert creds.enable_password == "enable1"


def test_update_blank_password_preserves(sched_env_with_key):
    sch = sched_env_with_key
    result = sch.create_schedule(
        "live",
        CSV_OK,
        mode=sch.MODE_LIVE,
        username="u1",
        password="keep-me",
    )
    s = result.schedule
    updated = sch.update_schedule(s.id, name="live-renamed", password=None)
    assert updated.schedule.name == "live-renamed"
    creds = sch.resolve_schedule_credentials(s.id)
    assert creds.password == "keep-me"


def test_migration_defaults_dry_mock(sched_env):
    sch = sched_env
    result = sch.create_schedule("legacy", CSV_OK)
    s = result.schedule
    assert s.mode == sch.MODE_DRY_MOCK

    with sqlite3.connect(str(sch.schedules_db_path())) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schedule_runs'",
        ).fetchone()
        assert row


def test_live_run_returns_phase_b_pending(sched_env):
    sch = sched_env
    result = sch.create_schedule(
        "live",
        CSV_OK,
        mode=sch.MODE_LIVE,
        username="u",
        password="p",
    )
    r = sch.run_schedule(result.schedule.id)
    assert r["ok"] is False
    assert "Phase B" in r.get("error", "")


def test_env_key_overrides_store_auto(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    env_key = Fernet.generate_key().decode()
    monkeypatch.setenv("NCCM_SECRETS_KEY", env_key)
    import importlib
    import nccm.backup.secrets as secrets
    import nccm.backup.schedule as sch

    importlib.reload(secrets)
    importlib.reload(sch)

    result = sch.create_schedule(
        "live",
        CSV_OK,
        mode=sch.MODE_LIVE,
        username="u",
        password="p",
    )
    assert result.key_created is False
    assert secrets.secrets_key_source() == "env"
    assert not secrets.store_master_key_path().exists()
