from __future__ import annotations

from pathlib import Path

import pytest

from web.deps import role_can_operate, role_can_view_schedules


def test_role_can_operate_matrix():
    assert role_can_operate("operator")
    assert role_can_operate("admin")
    assert not role_can_operate("viewer")
    assert not role_can_operate("")


def test_role_can_view_schedules_matrix():
    assert role_can_view_schedules("admin")
    assert role_can_view_schedules("operator")
    assert role_can_view_schedules("viewer")
    assert not role_can_view_schedules("")


def test_operator_role_create(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    monkeypatch.setenv("NCCM_AUTH_DB", str(store / "portal_auth.db"))
    import importlib

    import nccm.auth.db as adb
    import nccm.auth.service as svc

    importlib.reload(adb)
    importlib.reload(svc)
    adb.init_auth_db()
    u = svc.create_user("ops1", "password123456", role="operator")
    assert u.role == "operator"
