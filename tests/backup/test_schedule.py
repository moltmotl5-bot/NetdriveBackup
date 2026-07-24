from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from nccm.backup.reachability import ProbeResult, probe_device, probe_devices
from nccm.models import DeviceRow


@pytest.fixture()
def sched_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    monkeypatch.delenv("NCCM_SECRETS_KEY", raising=False)
    import importlib
    import nccm.backup.schedule as sch
    import nccm.backup.secrets as secrets

    importlib.reload(secrets)
    importlib.reload(sch)
    yield sch
    importlib.reload(secrets)
    importlib.reload(sch)


CSV_OK = """Site,IP,Vendor,Port
lab,10.0.0.1,huawei,22
lab,10.0.0.2,cisco,22
"""


def test_create_schedule_live_only(sched_env, monkeypatch: pytest.MonkeyPatch):
    sch = sched_env
    result = sch.create_schedule(
        "daily",
        CSV_OK,
        interval_days=1,
        username="admin",
        password="secret",
        csv_filename="lab.csv",
    )
    s = result.schedule
    assert s.interval_days == 1
    assert s.device_count == 2
    assert s.password_set is True
    assert result.key_created is True


def test_due_uses_days(sched_env):
    from datetime import datetime, timezone

    sch = sched_env
    result = sch.create_schedule(
        "daily",
        CSV_OK,
        interval_days=2,
        username="u",
        password="p",
    )
    s = result.schedule
    assert sch._due(s, 0) is True
    s2 = sch.Schedule(
        id=s.id,
        name=s.name,
        csv_text=s.csv_text,
        interval_days=2,
        enabled=True,
        username=s.username,
        password_set=True,
        enable_password_set=False,
        device_count=2,
        csv_filename="",
        devices_verified_at="",
        running_job_id="",
        last_run_at="2026-01-01T00:00:00Z",
        last_result="",
        last_ok_count=0,
        last_fail_count=0,
        created_by="",
    )
    last_ts = datetime.strptime("2026-01-01T00:00:00Z", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    assert sch._due(s2, last_ts + 86400) is False
    assert sch._due(s2, last_ts + 86400 * 2) is True


def test_probe_devices_mock(sched_env, monkeypatch: pytest.MonkeyPatch):
    devices = [
        DeviceRow(site="lab", ip="10.0.0.1", vendor="huawei", port=22),
        DeviceRow(site="lab", ip="10.0.0.2", vendor="cisco", port=22),
    ]

    def fake_probe(self, *, ip, port=22, timeout=3.0):
        ok = ip == "10.0.0.1"
        return {"ok": ok, "latency_ms": 5 if ok else 0, "msg": "" if ok else "timeout"}

    monkeypatch.setattr("nccm.netdriver.client.NetDriverClient.probe", fake_probe)
    results = probe_devices(devices)
    assert len(results) == 2
    assert results[0].ok is True
    assert results[1].ok is False


def test_draft_confirm_only_ok_devices(sched_env, monkeypatch: pytest.MonkeyPatch):
    import importlib
    import nccm.backup.schedule_draft as draft_mod

    importlib.reload(draft_mod)

    def fake_probe(self, *, ip, port=22, timeout=3.0):
        ok = ip.endswith(".1")
        return {"ok": ok, "latency_ms": 1 if ok else 0, "msg": "" if ok else "fail"}

    monkeypatch.setattr("nccm.netdriver.client.NetDriverClient.probe", fake_probe)
    d = draft_mod.create_draft_from_upload(
        name="t",
        csv_bytes=CSV_OK.encode(),
        csv_filename="lab.csv",
        interval_days=1,
        username="u",
        password="p",
    )
    assert d.ok_count == 1
    result = draft_mod.confirm_draft(d.id)
    assert result.schedule.device_count == 1
    assert "10.0.0.1" in result.schedule.csv_text
    assert "10.0.0.2" not in result.schedule.csv_text


def test_execute_schedule_starts_job(sched_env, monkeypatch: pytest.MonkeyPatch):
    from nccm.backup import schedule_executor as ex

    sch = sched_env
    result = sch.create_schedule("daily", CSV_OK, interval_days=1, username="u", password="p")
    sid = result.schedule.id

    mock_job = MagicMock()
    mock_job.status = "running"
    monkeypatch.setattr(
        "nccm.backup.schedule_executor.start_backup_job_async",
        lambda *a, **k: "job-123",
    )
    monkeypatch.setattr("nccm.backup.schedule_executor.get_job", lambda _jid: mock_job)

    out = ex.execute_schedule(sid, triggered_by="test")
    assert out["ok"] is True
    assert out["job_id"] == "job-123"


def test_list_schedule_runs(sched_env):
    from nccm.backup.schedule_executor import MODE_LIVE, _connect, _insert_run

    sch = sched_env
    result = sch.create_schedule("daily", CSV_OK, interval_days=1, username="u", password="p")
    sid = result.schedule.id
    with _connect() as conn:
        _insert_run(
            conn,
            schedule_id=sid,
            mode=MODE_LIVE,
            status="done",
            triggered_by="manual",
            summary="live ok 2/2",
            device_count=2,
            job_id="job-abc",
        )
    runs = sch.list_schedule_runs()
    assert len(runs) == 1
    assert runs[0].schedule_name == "daily"
    assert runs[0].schedule_id == sid
    assert runs[0].status == "done"
    assert runs[0].triggered_by == "manual"
    assert runs[0].job_id == "job-abc"

    filtered = sch.list_schedule_runs(schedule_id=sid, limit=5)
    assert len(filtered) == 1
    assert filtered[0].schedule_id == sid
    assert sch.list_schedule_runs(schedule_id=999) == []
