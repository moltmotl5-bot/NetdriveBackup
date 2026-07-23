from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def sched_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    import importlib
    import nccm.backup.schedule as sch

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
    s = sch.create_schedule("lab", CSV_OK, every_minutes=30)
    assert s.id > 0
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
