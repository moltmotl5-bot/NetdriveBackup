from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture()
def token_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    monkeypatch.setenv("NCCM_AUTH_DB", str(store / "portal_auth.db"))
    monkeypatch.setenv("NCCM_AUDIT_DB", str(store / "audit" / "audit.db"))
    import importlib

    import nccm.auth.api_tokens as ts
    import nccm.auth.audit as audit
    import nccm.auth.db as adb
    import nccm.config as cfg

    importlib.reload(cfg)
    importlib.reload(adb)
    importlib.reload(audit)
    importlib.reload(ts)
    adb.init_auth_db()
    yield ts, audit, store


def test_create_token_sets_expires(token_env):
    ts, audit, store = token_env
    tok, plain = ts.create_token("t1", expires_days=30)
    assert plain.startswith("nccm_")
    assert tok.expires_at
    assert not tok.is_expired
    exp = datetime.fromisoformat(tok.expires_at.replace("Z", "+00:00"))
    assert exp > datetime.now(timezone.utc) + timedelta(days=25)


def test_expired_token_rejected(token_env):
    ts, _audit, _store = token_env
    tok, plain = ts.create_token("t2", expires_days=1)
    # force expire via DB
    from nccm.auth import db as auth_db

    past = "2020-01-01T00:00:00Z"
    with auth_db.connect() as conn:
        conn.execute(
            "UPDATE api_tokens SET expires_at = ? WHERE id = ?",
            (past, tok.id),
        )
    assert ts.authenticate_api_key(plain) is None
    assert ts.last_auth_failure_reason() == "token_expired"
    assert ts.active_token_count() == 0


def test_null_expires_treated_expired(token_env):
    ts, _a, _s = token_env
    tok, plain = ts.create_token("t3", expires_days=7)
    from nccm.auth import db as auth_db

    with auth_db.connect() as conn:
        conn.execute(
            "UPDATE api_tokens SET expires_at = NULL WHERE id = ?",
            (tok.id,),
        )
    assert ts.authenticate_api_key(plain) is None
    assert ts.last_auth_failure_reason() == "token_expired"


def test_audit_written_under_store(token_env):
    ts, audit, store = token_env
    audit.write_audit(event="unit_test", success=True, actor="tester", detail="hi")
    dbp = store / "audit" / "audit.db"
    assert dbp.is_file()
    rows = audit.list_audit_events(limit=10)
    assert any(r.event == "unit_test" and r.actor == "tester" for r in rows)
    csv = audit.export_audit_csv(limit=10)
    assert "unit_test" in csv


def test_ttl_bounds(token_env):
    ts, _a, _s = token_env
    with pytest.raises(ValueError):
        ts.create_token("bad", expires_days=0)
    with pytest.raises(ValueError):
        ts.create_token("bad", expires_days=9999)
