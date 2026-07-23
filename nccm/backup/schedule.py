"""Scheduled backup jobs: CSV list + dry/mock run (no SSH / no Agent)."""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from nccm.config import store_dir
from nccm.registry.csv import load_devices_csv


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def schedules_db_path() -> Path:
    return store_dir() / "schedules.db"


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = schedules_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                csv_text TEXT NOT NULL,
                every_minutes INTEGER NOT NULL DEFAULT 60,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_run_at TEXT,
                last_result TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        yield conn
        conn.commit()
    finally:
        conn.close()


@dataclass(frozen=True)
class Schedule:
    id: int
    name: str
    csv_text: str
    every_minutes: int
    enabled: bool
    last_run_at: str
    last_result: str


def _row(r: sqlite3.Row) -> Schedule:
    return Schedule(
        id=int(r["id"]),
        name=str(r["name"]),
        csv_text=str(r["csv_text"] or ""),
        every_minutes=int(r["every_minutes"] or 60),
        enabled=bool(r["enabled"]),
        last_run_at=str(r["last_run_at"] or ""),
        last_result=str(r["last_result"] or ""),
    )


def list_schedules() -> list[Schedule]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM schedules ORDER BY id").fetchall()
    return [_row(r) for r in rows]


def get_schedule(schedule_id: int) -> Schedule | None:
    with _connect() as conn:
        r = conn.execute("SELECT * FROM schedules WHERE id = ?", (int(schedule_id),)).fetchone()
    return _row(r) if r else None


def create_schedule(name: str, csv_text: str, every_minutes: int = 60) -> Schedule:
    name = (name or "").strip() or "schedule"
    body = (csv_text or "").strip()
    if not body:
        raise ValueError("csv_text required")
    # Validate parse
    mock_run_csv(body)
    mins = max(1, int(every_minutes))
    now = _utc_now()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO schedules (name, csv_text, every_minutes, enabled, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (name, body, mins, now, now),
        )
        sid = int(cur.lastrowid)
    got = get_schedule(sid)
    assert got
    return got


def set_enabled(schedule_id: int, enabled: bool) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE schedules SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, _utc_now(), int(schedule_id)),
        )


def delete_schedule(schedule_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM schedules WHERE id = ?", (int(schedule_id),))


def mock_run_csv(csv_text: str) -> dict:
    """Parse CSV and return dry-run summary — never connects to devices."""
    body = (csv_text or "").strip()
    if not body:
        raise ValueError("empty csv")
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
        tmp.write(body)
        path = Path(tmp.name)
    try:
        devices = load_devices_csv(path)
    finally:
        path.unlink(missing_ok=True)
    return {
        "mode": "dry-mock",
        "device_count": len(devices),
        "devices": [
            {
                "site": d.site,
                "ip": d.ip,
                "hostname": d.hostname_hint or "",
                "vendor": d.vendor,
            }
            for d in devices
        ],
        "message": "mock only — no SSH / no Agent",
    }


def run_schedule(schedule_id: int) -> dict:
    sch = get_schedule(schedule_id)
    if not sch:
        raise ValueError("schedule not found")
    try:
        result = mock_run_csv(sch.csv_text)
        summary = f"ok mock {result['device_count']} devices"
        ok = True
    except Exception as exc:  # noqa: BLE001 — surface to last_result
        result = {"mode": "dry-mock", "error": str(exc)}
        summary = f"error: {exc}"
        ok = False
    now = _utc_now()
    with _connect() as conn:
        conn.execute(
            "UPDATE schedules SET last_run_at = ?, last_result = ?, updated_at = ? WHERE id = ?",
            (now, summary[:500], now, int(schedule_id)),
        )
    result["ok"] = ok
    result["schedule_id"] = schedule_id
    result["ran_at"] = now
    return result


_watcher_started = False
_watcher_lock = threading.Lock()


def _due(sch: Schedule, now_ts: float) -> bool:
    if not sch.enabled:
        return False
    if not sch.last_run_at:
        return True
    try:
        # 2026-07-23T10:00:00Z
        last = datetime.strptime(sch.last_run_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        elapsed = now_ts - last.timestamp()
        return elapsed >= sch.every_minutes * 60
    except ValueError:
        return True


def tick_schedules() -> list[dict]:
    """Run all due schedules (mock)."""
    now_ts = time.time()
    out: list[dict] = []
    for sch in list_schedules():
        if _due(sch, now_ts):
            out.append(run_schedule(sch.id))
    return out


def start_schedule_watcher(*, interval_sec: float = 30.0) -> None:
    """Daemon thread — call once from app startup."""
    global _watcher_started
    with _watcher_lock:
        if _watcher_started:
            return
        _watcher_started = True

    def _loop() -> None:
        while True:
            try:
                tick_schedules()
            except Exception:
                pass
            time.sleep(interval_sec)

    t = threading.Thread(target=_loop, name="nccm-schedule-watcher", daemon=True)
    t.start()
