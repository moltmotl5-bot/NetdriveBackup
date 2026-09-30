from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture()
def store_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    import importlib
    import nccm.config as cfg
    import nccm.storage.store_paths as sp

    importlib.reload(cfg)
    importlib.reload(sp)
    yield store, sp


def test_resolve_inside_store_ok(store_env):
    store, sp = store_env
    child = store / "lab" / "10.0.0.1__sw1"
    child.mkdir(parents=True)
    resolved = sp.resolve_inside_store(child)
    assert resolved == child.resolve()


def test_resolve_rejects_outside(store_env):
    store, sp = store_env
    outside = store.parent / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(sp.SecurityError):
        sp.resolve_inside_store(outside)


def test_resolve_rejects_traversal_from_db(store_env):
    store, sp = store_env
    evil = store / ".." / "escape"
    with pytest.raises(sp.SecurityError):
        sp.resolve_snapshot_dir(str(evil))


def test_symlink_escape_rejected(store_env):
    store, sp = store_env
    outside = store_env[0].parent / "secret"
    outside.mkdir()
    link = store / "link"
    link.symlink_to(outside)
    with pytest.raises(sp.SecurityError):
        sp.resolve_inside_store(link)
