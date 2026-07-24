"""Schedule CSV upload draft: parse, probe, confirm."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from nccm.backup.reachability import ProbeResult, probe_devices
from nccm.backup.schedule import ScheduleWriteResult, create_schedule, get_schedule, update_schedule
from nccm.config import store_dir
from nccm.registry.csv import devices_to_csv, load_devices_csv_text

_DRAFT_TTL_HOURS = 2


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _drafts_db_path() -> Path:
    return store_dir() / "schedules.db"


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = _drafts_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schedule_drafts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                interval_days INTEGER NOT NULL DEFAULT 1,
                username TEXT NOT NULL DEFAULT '',
                password TEXT NOT NULL DEFAULT '',
                enable_password TEXT NOT NULL DEFAULT '',
                csv_filename TEXT NOT NULL DEFAULT '',
                csv_original TEXT NOT NULL,
                probe_json TEXT NOT NULL,
                edit_schedule_id INTEGER,
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        yield conn
        conn.commit()
    finally:
        conn.close()


@dataclass(frozen=True)
class ProbeRowView:
    site: str
    ip: str
    vendor: str
    port: int
    ok: bool
    latency_ms: int
    error: str


@dataclass(frozen=True)
class ScheduleDraft:
    id: str
    name: str
    interval_days: int
    username: str
    csv_filename: str
    rows: list[ProbeRowView]
    ok_count: int
    fail_count: int
    edit_schedule_id: int | None
    created_by: str


def _purge_expired(conn: sqlite3.Connection) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=_DRAFT_TTL_HOURS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    conn.execute("DELETE FROM schedule_drafts WHERE created_at < ?", (cutoff,))


def _probe_to_view(result: ProbeResult) -> ProbeRowView:
    d = result.device
    return ProbeRowView(
        site=d.site,
        ip=d.ip,
        vendor=d.vendor,
        port=d.port or 22,
        ok=result.ok,
        latency_ms=result.latency_ms,
        error=result.error,
    )


def _serialize_probe(results: list[ProbeResult]) -> str:
    payload = []
    for r in results:
        d = r.device
        payload.append(
            {
                "site": d.site,
                "ip": d.ip,
                "vendor": d.vendor,
                "port": d.port or 22,
                "model": d.model,
                "version": d.version,
                "hostname_hint": d.hostname_hint,
                "ok": r.ok,
                "latency_ms": r.latency_ms,
                "error": r.error,
            }
        )
    return json.dumps(payload, ensure_ascii=False)


def _deserialize_probe(raw: str) -> list[tuple]:
    from nccm.models import DeviceRow

    rows = json.loads(raw or "[]")
    out: list[tuple] = []
    for item in rows:
        dev = DeviceRow(
            site=str(item.get("site") or ""),
            ip=str(item.get("ip") or ""),
            vendor=str(item.get("vendor") or ""),
            model=item.get("model") or None,
            version=item.get("version") or None,
            hostname_hint=item.get("hostname_hint") or None,
            port=int(item.get("port") or 22),
        )
        view = ProbeRowView(
            site=dev.site,
            ip=dev.ip,
            vendor=dev.vendor,
            port=dev.port or 22,
            ok=bool(item.get("ok")),
            latency_ms=int(item.get("latency_ms") or 0),
            error=str(item.get("error") or ""),
        )
        out.append((dev, view))
    return out


def create_draft_from_upload(
    *,
    name: str,
    csv_bytes: bytes,
    csv_filename: str,
    interval_days: int,
    username: str,
    password: str,
    enable_password: str = "",
    created_by: str = "",
    edit_schedule_id: int | None = None,
) -> ScheduleDraft:
    body = csv_bytes.decode("utf-8-sig", errors="replace").strip()
    if not body:
        raise ValueError("CSV 檔案為空")
    devices = load_devices_csv_text(body)
    if not devices:
        raise ValueError("CSV 無有效設備列")
    if not (username or "").strip():
        raise ValueError("SSH 帳號必填")
    if not (password or ""):
        raise ValueError("SSH 密碼必填")

    results = probe_devices(devices)
    draft_id = str(uuid.uuid4())
    now = _utc_now()
    with _connect() as conn:
        _purge_expired(conn)
        conn.execute(
            """
            INSERT INTO schedule_drafts (
                id, name, interval_days, username, password, enable_password,
                csv_filename, csv_original, probe_json, edit_schedule_id,
                created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft_id,
                (name or "").strip() or "schedule",
                max(1, int(interval_days)),
                (username or "").strip(),
                password,
                enable_password or "",
                (csv_filename or "upload.csv").strip()[:200],
                body,
                _serialize_probe(results),
                int(edit_schedule_id) if edit_schedule_id else None,
                (created_by or "").strip()[:128],
                now,
            ),
        )
    return get_draft(draft_id)


def get_draft(draft_id: str) -> ScheduleDraft:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM schedule_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
    if not row:
        raise ValueError("draft not found")
    pairs = _deserialize_probe(str(row["probe_json"] or "[]"))
    views = [v for _d, v in pairs]
    ok_count = sum(1 for v in views if v.ok)
    return ScheduleDraft(
        id=str(row["id"]),
        name=str(row["name"]),
        interval_days=int(row["interval_days"] or 1),
        username=str(row["username"] or ""),
        csv_filename=str(row["csv_filename"] or ""),
        rows=views,
        ok_count=ok_count,
        fail_count=len(views) - ok_count,
        edit_schedule_id=int(row["edit_schedule_id"]) if row["edit_schedule_id"] else None,
        created_by=str(row["created_by"] or ""),
    )


def confirm_draft(draft_id: str) -> ScheduleWriteResult:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM schedule_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
        if not row:
            raise ValueError("draft not found")
        pairs = _deserialize_probe(str(row["probe_json"] or "[]"))
        ok_devices = [d for d, v in pairs if v.ok]
        if not ok_devices:
            raise ValueError("無任何設備通過連線測試，無法建立排程")
        csv_text = devices_to_csv(ok_devices)
        edit_id = int(row["edit_schedule_id"]) if row["edit_schedule_id"] else None
        conn.execute("DELETE FROM schedule_drafts WHERE id = ?", (draft_id,))

    if edit_id:
        result = update_schedule(
            edit_id,
            name=str(row["name"]),
            csv_text=csv_text,
            interval_days=int(row["interval_days"] or 1),
            username=str(row["username"] or ""),
            password=str(row["password"] or ""),
            enable_password=str(row["enable_password"] or "") or None,
            csv_filename=str(row["csv_filename"] or ""),
        )
    else:
        result = create_schedule(
            str(row["name"]),
            csv_text,
            interval_days=int(row["interval_days"] or 1),
            username=str(row["username"] or ""),
            password=str(row["password"] or ""),
            enable_password=str(row["enable_password"] or ""),
            created_by=str(row["created_by"] or ""),
            csv_filename=str(row["csv_filename"] or ""),
        )
    return result


def delete_draft(draft_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM schedule_drafts WHERE id = ?", (draft_id,))
