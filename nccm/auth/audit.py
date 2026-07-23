"""Append-only audit log under store/audit/ (SQLite)."""
from __future__ import annotations

import csv
import io
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from starlette.requests import Request

from nccm.config import store_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    ip TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT '',
    event TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_events(event);
"""


def audit_db_path() -> Path:
    override = __import__("os").environ.get("NCCM_AUDIT_DB", "").strip()
    if override:
        return Path(override)
    d = store_dir() / "audit"
    d.mkdir(parents=True, exist_ok=True)
    return d / "audit.db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = audit_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def client_ip(request: Request | None) -> str:
    if request is None:
        return ""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client:
        return request.client.host[:64]
    return "unknown"


def _clean(s: str, n: int) -> str:
    return (s or "").replace("\n", " ").replace("\r", " ").strip()[:n]


def write_audit(
    *,
    event: str,
    success: bool,
    actor: str = "",
    detail: str = "",
    ip: str = "",
    request: Request | None = None,
) -> None:
    """Persist one audit row. Never raises to callers."""
    try:
        ts = _utc_now()
        ip_s = _clean(ip or client_ip(request), 64)
        actor_s = _clean(actor, 128)
        event_s = _clean(event, 64) or "unknown"
        detail_s = _clean(detail, 512)
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (ts, ip, actor, event, success, detail)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ts, ip_s, actor_s, event_s, 1 if success else 0, detail_s),
            )
    except Exception:
        pass


def audit_portal_login(request: Request, username: str, success: bool) -> None:
    write_audit(
        request=request,
        event="portal_login",
        success=success,
        actor=username or "",
        detail="ok" if success else "failed",
    )


def audit_api_token_event(
    request: Request,
    *,
    event: str,
    token_name: str,
    success: bool,
    detail: str = "",
) -> None:
    write_audit(
        request=request,
        event=event,
        success=success,
        actor=token_name or "",
        detail=detail,
    )


@dataclass(frozen=True)
class AuditEvent:
    id: int
    ts: str
    ip: str
    actor: str
    event: str
    success: bool
    detail: str


def list_audit_events(
    *,
    limit: int = 200,
    offset: int = 0,
    event: str = "",
) -> list[AuditEvent]:
    limit = max(1, min(int(limit), 2000))
    offset = max(0, int(offset))
    sql = "SELECT * FROM audit_events WHERE 1=1"
    args: list = []
    if event.strip():
        sql += " AND event = ?"
        args.append(event.strip())
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args.extend([limit, offset])
    with _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [
        AuditEvent(
            id=int(r["id"]),
            ts=str(r["ts"]),
            ip=str(r["ip"] or ""),
            actor=str(r["actor"] or ""),
            event=str(r["event"] or ""),
            success=bool(r["success"]),
            detail=str(r["detail"] or ""),
        )
        for r in rows
    ]


def export_audit_csv(*, limit: int = 5000, event: str = "") -> str:
    rows = list_audit_events(limit=limit, offset=0, event=event)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "ts", "ip", "actor", "event", "success", "detail"])
    for r in rows:
        w.writerow([r.id, r.ts, r.ip, r.actor, r.event, int(r.success), r.detail])
    return buf.getvalue()
