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
    import importlib
    import nccm.config as cfg
    import nccm.storage.index_db as idx
    import nccm.storage.retention as ret

    importlib.reload(cfg)
    importlib.reload(idx)
    importlib.reload(ret)
    yield store, idx, ret


def test_execute_requires_token(store_env):
    store, idx, ret = store_env
    did = idx.device_id("lab", "10.0.0.1", 22, "LAB-SW1")
    _seed_snaps(idx, store, did, 4)
    plan = ret.plan_retention(keep_last=2)
    with pytest.raises(ret.RetentionError, match="confirm_token"):
        ret.apply_retention(plan, dry_run=False)


def test_dry_run_token_then_execute(store_env):
    store, idx, ret = store_env
    did = idx.device_id("lab", "10.0.0.1", 22, "LAB-SW1")
    _seed_snaps(idx, store, did, 5)
    plan = ret.plan_retention(keep_last=2)
    token = ret.issue_retention_token(plan, device_id=None)
    dry = ret.apply_retention(plan, dry_run=True)
    assert dry["would_delete"] == 3
    out = ret.apply_retention(plan, dry_run=False, confirm_token=token, device_id=None)
    assert out["deleted"] == 3
    assert len(idx.list_snapshots_for_device(did)) == 2


def test_reject_outside_store_path_on_delete(store_env, monkeypatch: pytest.MonkeyPatch):
    store, idx, ret = store_env
    did = idx.device_id("lab", "10.0.0.1", 22, "LAB-SW1")
    _seed_snaps(idx, store, did, 3)
    outside = store.parent / "evil"
    outside.mkdir()
    (outside / "config.txt").write_text("x\n", encoding="utf-8")
    plan = ret.plan_retention(keep_last=1)
    # tamper candidate path in plan (simulate poisoned DB)
    evil = ret.RetentionPlan(
        keep_last=plan.keep_last,
        candidates=[
            ret.RetentionCandidate(
                device_id=did,
                snapshot_id=plan.candidates[0].snapshot_id,
                snapshot_path=str(outside),
                created_at=plan.candidates[0].created_at,
            )
        ],
        dry_run=True,
    )
    token = ret.issue_retention_token(evil, device_id=None)
    out = ret.apply_retention(evil, dry_run=False, confirm_token=token, device_id=None)
    assert out["deleted"] == 0
    assert str(outside) in out["skipped"]


def _seed_snaps(idx, store: Path, device_id: str, n: int):
    site_dir = store / "lab" / "10.0.0.1__LAB-SW1" / "snapshots"
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
            "port": 22,
            "created_at": f"2026-01-{i+1:02d}T00:00:00Z",
        }
        idx.index_manifest(manifest, snap)
