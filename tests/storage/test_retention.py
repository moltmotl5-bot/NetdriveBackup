from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture()
def store_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    monkeypatch.setenv("NCCM_AUTH_DB", str(store / "portal_auth.db"))
    # reload path helpers
    import nccm.config as cfg
    import nccm.storage.index_db as idx
    import nccm.storage.retention as ret
    import importlib

    importlib.reload(cfg)
    importlib.reload(idx)
    importlib.reload(ret)
    yield store, idx, ret


def test_plan_keeps_newest(store_env):
    store, idx, ret = store_env
    did = idx.device_id("lab", "10.0.0.1", 22, "LAB-SW1")
    _seed_snaps(idx, store, did, 5)
    plan = ret.plan_retention(keep_last=2)
    assert len(plan.candidates) == 3
    dry = ret.apply_retention(plan, dry_run=True)
    assert dry["would_delete"] == 3
    out = ret.apply_retention(plan, dry_run=False)
    assert out["deleted"] == 3
    snaps = idx.list_snapshots_for_device(did)
    assert len(snaps) == 2


def _seed_snaps(idx, store: Path, device_id: str, n: int):
    site_dir = store / "lab" / "10.0.0.1"
    for i in range(n):
        snap = site_dir / f"2026-01-{i+1:02d}T00-00-00Z"
        snap.mkdir(parents=True)
        (snap / "config.txt").write_text(f"cfg-{i}\n", encoding="utf-8")
        (snap / "version_info.txt").write_text("SW Version: 1.0\n", encoding="utf-8")
        manifest = {
            "site": "lab",
            "ip": "10.0.0.1",
            "hostname": "LAB-SW1",
            "vendor": "huawei",
            "status": "ok",
            "ssh_port": 22,
            "created_at": f"2026-01-{i+1:02d}T00:00:00Z",
        }
        idx.index_manifest(manifest, snap)
