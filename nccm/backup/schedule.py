"""Scheduled backup jobs: daily interval, encrypted credentials, live execution."""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from nccm.backup.secrets import (
    KeyEnsureResult,
    SecretsKeyWriteError,
    SecretsNotConfiguredError,
    decrypt,
    encrypt,
    ensure_master_key,
    secrets_configured,
)
from nccm.config import store_dir
from nccm.registry.csv import load_devices_csv_text

MODE_LIVE = "live"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def schedules_db_path() -> Path:
    return store_dir() / "schedules.db"


def schedule_lock_path() -> Path:
    return store_dir() / "schedule.lock"


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(r[1]) for r in rows}


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            csv_text TEXT NOT NULL,
            every_minutes INTEGER NOT NULL DEFAULT 1440,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_run_at TEXT,
            last_result TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cols = _table_columns(conn, "schedules")
    for name, ddl in (
        ("mode", "TEXT NOT NULL DEFAULT 'live'"),
        ("username", "TEXT NOT NULL DEFAULT ''"),
        ("password_enc", "TEXT NOT NULL DEFAULT ''"),
        ("enable_password_enc", "TEXT NOT NULL DEFAULT ''"),
        ("running_job_id", "TEXT NOT NULL DEFAULT ''"),
        ("last_job_id", "TEXT NOT NULL DEFAULT ''"),
        ("last_ok_count", "INTEGER NOT NULL DEFAULT 0"),
        ("last_fail_count", "INTEGER NOT NULL DEFAULT 0"),
        ("created_by", "TEXT NOT NULL DEFAULT ''"),
        ("interval_days", "INTEGER NOT NULL DEFAULT 1"),
        ("csv_filename", "TEXT NOT NULL DEFAULT ''"),
        ("device_count", "INTEGER NOT NULL DEFAULT 0"),
        ("devices_verified_at", "TEXT NOT NULL DEFAULT ''"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE schedules ADD COLUMN {name} {ddl}")
    if "interval_days" in _table_columns(conn, "schedules") and "every_minutes" in cols:
        conn.execute(
            """
            UPDATE schedules SET interval_days = MAX(1, every_minutes / 1440)
            WHERE interval_days IS NULL OR interval_days < 1
            """
        )
    conn.execute("UPDATE schedules SET mode = 'live' WHERE mode IS NULL OR mode = '' OR mode = 'dry_mock'")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            mode TEXT NOT NULL,
            job_id TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            ok_count INTEGER NOT NULL DEFAULT 0,
            fail_count INTEGER NOT NULL DEFAULT 0,
            device_count INTEGER NOT NULL DEFAULT 0,
            summary TEXT NOT NULL DEFAULT '',
            triggered_by TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_schedule_runs_schedule ON schedule_runs(schedule_id, started_at DESC)"
    )


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = schedules_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_schema(conn)
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
    interval_days: int
    enabled: bool
    username: str
    password_set: bool
    enable_password_set: bool
    device_count: int
    csv_filename: str
    devices_verified_at: str
    running_job_id: str
    last_run_at: str
    last_result: str
    last_ok_count: int
    last_fail_count: int
    created_by: str


@dataclass(frozen=True)
class ScheduleCredentials:
    username: str
    password: str
    enable_password: str


@dataclass(frozen=True)
class ScheduleWriteResult:
    schedule: Schedule
    key_created: bool = False
    key_source: str = ""


def _interval_days_from_row(r: sqlite3.Row) -> int:
    if "interval_days" in r.keys() and r["interval_days"] is not None:
        return max(1, int(r["interval_days"]))
    mins = int(r["every_minutes"] or 1440) if "every_minutes" in r.keys() else 1440
    return max(1, mins // 1440)


def _row(r: sqlite3.Row) -> Schedule:
    password_enc = str(r["password_enc"] or "")
    enable_enc = str(r["enable_password_enc"] or "")
    device_count = int(r["device_count"] or 0) if "device_count" in r.keys() else 0
    if device_count <= 0:
        try:
            device_count = len(load_devices_csv_text(str(r["csv_text"] or "")))
        except ValueError:
            device_count = 0
    return Schedule(
        id=int(r["id"]),
        name=str(r["name"]),
        csv_text=str(r["csv_text"] or ""),
        interval_days=_interval_days_from_row(r),
        enabled=bool(r["enabled"]),
        username=str(r["username"] or ""),
        password_set=bool(password_enc.strip()),
        enable_password_set=bool(enable_enc.strip()),
        device_count=device_count,
        csv_filename=str(r["csv_filename"] or "") if "csv_filename" in r.keys() else "",
        devices_verified_at=str(r["devices_verified_at"] or "") if "devices_verified_at" in r.keys() else "",
        running_job_id=str(r["running_job_id"] or "") if "running_job_id" in r.keys() else "",
        last_run_at=str(r["last_run_at"] or ""),
        last_result=str(r["last_result"] or ""),
        last_ok_count=int(r["last_ok_count"] or 0) if "last_ok_count" in r.keys() else 0,
        last_fail_count=int(r["last_fail_count"] or 0) if "last_fail_count" in r.keys() else 0,
        created_by=str(r["created_by"] or ""),
    )


def _validate_credentials(*, username: str, password_enc: str, password_plain: str | None) -> None:
    user = (username or "").strip()
    has_password = bool((password_enc or "").strip()) or bool(password_plain)
    if not user or not has_password:
        raise ValueError("SSH 帳號與密碼必填")


def _prepare_credential_storage(
    *,
    username: str,
    password: str,
    enable_password: str,
    password_enc: str = "",
    enable_enc: str = "",
) -> tuple[str, str, str, KeyEnsureResult | None]:
    _validate_credentials(
        username=username,
        password_enc=password_enc,
        password_plain=password or None,
    )
    key_result: KeyEnsureResult | None = None
    if bool(password) or bool(enable_password) or not secrets_configured():
        try:
            key_result = ensure_master_key()
        except SecretsKeyWriteError as exc:
            raise ValueError(str(exc)) from exc
    out_pass = encrypt(password) if password else password_enc
    out_enable = encrypt(enable_password) if enable_password else enable_enc
    return (username or "").strip(), out_pass, out_enable, key_result


def _validate_csv(csv_text: str) -> list:
    body = (csv_text or "").strip()
    if not body:
        raise ValueError("csv_text required")
    devices = load_devices_csv_text(body)
    if not devices:
        raise ValueError("CSV 無有效設備")
    return devices


def list_schedules() -> list[Schedule]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM schedules ORDER BY id").fetchall()
    return [_row(r) for r in rows]


def get_schedule(schedule_id: int) -> Schedule | None:
    with _connect() as conn:
        r = conn.execute("SELECT * FROM schedules WHERE id = ?", (int(schedule_id),)).fetchone()
    return _row(r) if r else None


def _get_schedule_row(conn: sqlite3.Connection, schedule_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM schedules WHERE id = ?", (int(schedule_id),)).fetchone()


def load_schedule_devices(schedule: Schedule) -> list[dict]:
    devices = load_devices_csv_text(schedule.csv_text)
    return [
        {
            "site": d.site,
            "ip": d.ip,
            "vendor": d.vendor,
            "port": d.port or 22,
            "hostname": d.hostname_hint or "",
        }
        for d in devices
    ]


def create_schedule(
    name: str,
    csv_text: str,
    *,
    interval_days: int = 1,
    username: str = "",
    password: str = "",
    enable_password: str = "",
    created_by: str = "",
    csv_filename: str = "",
) -> ScheduleWriteResult:
    name = (name or "").strip() or "schedule"
    devices = _validate_csv(csv_text)
    days = max(1, int(interval_days))
    user, password_enc, enable_enc, key_result = _prepare_credential_storage(
        username=username,
        password=password,
        enable_password=enable_password,
    )
    now = _utc_now()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO schedules (
                name, csv_text, every_minutes, interval_days, enabled, mode,
                username, password_enc, enable_password_enc,
                csv_filename, device_count, devices_verified_at,
                created_by, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                csv_text.strip(),
                days * 1440,
                days,
                MODE_LIVE,
                user,
                password_enc,
                enable_enc,
                (csv_filename or "").strip()[:200],
                len(devices),
                now,
                (created_by or "").strip()[:128],
                now,
                now,
            ),
        )
        sid = int(cur.lastrowid)
    got = get_schedule(sid)
    assert got
    return ScheduleWriteResult(
        schedule=got,
        key_created=bool(key_result and key_result.created),
        key_source=key_result.source if key_result else "",
    )


def update_schedule(
    schedule_id: int,
    *,
    name: str | None = None,
    csv_text: str | None = None,
    interval_days: int | None = None,
    username: str | None = None,
    password: str | None = None,
    enable_password: str | None = None,
    csv_filename: str | None = None,
) -> ScheduleWriteResult:
    key_result: KeyEnsureResult | None = None
    with _connect() as conn:
        row = _get_schedule_row(conn, int(schedule_id))
        if not row:
            raise ValueError("schedule not found")

        new_name = (name if name is not None else str(row["name"])).strip() or "schedule"
        new_csv = (csv_text if csv_text is not None else str(row["csv_text"] or "")).strip()
        devices = _validate_csv(new_csv)
        new_days = max(1, int(interval_days if interval_days is not None else _interval_days_from_row(row)))
        new_user = (username if username is not None else str(row["username"] or "")).strip()
        new_filename = (
            csv_filename if csv_filename is not None else str(row["csv_filename"] or "")
        ).strip()[:200]

        password_enc = str(row["password_enc"] or "")
        enable_enc = str(row["enable_password_enc"] or "")
        if password is not None:
            password_enc = encrypt(password) if password else ""
        if enable_password is not None:
            enable_enc = encrypt(enable_password) if enable_password else ""

        if password is not None or enable_password is not None or not secrets_configured():
            new_user, password_enc, enable_enc, key_result = _prepare_credential_storage(
                username=new_user,
                password=password if password is not None else "",
                enable_password=enable_password if enable_password is not None else "",
                password_enc=password_enc if password is None else "",
                enable_enc=enable_enc if enable_password is None else "",
            )
        else:
            _validate_credentials(
                username=new_user,
                password_enc=password_enc,
                password_plain=None,
            )

        now = _utc_now()
        conn.execute(
            """
            UPDATE schedules SET
                name = ?, csv_text = ?, every_minutes = ?, interval_days = ?, mode = ?,
                username = ?, password_enc = ?, enable_password_enc = ?,
                csv_filename = ?, device_count = ?, devices_verified_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_name,
                new_csv,
                new_days * 1440,
                new_days,
                MODE_LIVE,
                new_user,
                password_enc,
                enable_enc,
                new_filename,
                len(devices),
                now,
                now,
                int(schedule_id),
            ),
        )
    got = get_schedule(int(schedule_id))
    assert got
    return ScheduleWriteResult(
        schedule=got,
        key_created=bool(key_result and key_result.created),
        key_source=key_result.source if key_result else "",
    )


def resolve_schedule_credentials(schedule_id: int) -> ScheduleCredentials:
    with _connect() as conn:
        row = _get_schedule_row(conn, int(schedule_id))
        if not row:
            raise ValueError("schedule not found")
        user = str(row["username"] or "").strip()
        password_enc = str(row["password_enc"] or "")
        enable_enc = str(row["enable_password_enc"] or "")
        _validate_credentials(username=user, password_enc=password_enc, password_plain=None)
        try:
            password = decrypt(password_enc)
            enable_password = decrypt(enable_enc) if enable_enc.strip() else ""
        except SecretsNotConfiguredError as exc:
            raise ValueError(str(exc)) from exc
        return ScheduleCredentials(
            username=user,
            password=password,
            enable_password=enable_password,
        )


def set_enabled(schedule_id: int, enabled: bool) -> None:
    sch = get_schedule(schedule_id)
    if not sch:
        raise ValueError("schedule not found")
    if enabled:
        if not secrets_configured():
            raise ValueError("加密主金鑰遺失或無法讀取，無法啟用排程")
        if not sch.username.strip() or not sch.password_set:
            raise ValueError("排程缺少 SSH 帳密，無法啟用")
    with _connect() as conn:
        conn.execute(
            "UPDATE schedules SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, _utc_now(), int(schedule_id)),
        )


def delete_schedule(schedule_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM schedule_runs WHERE schedule_id = ?", (int(schedule_id),))
        conn.execute("DELETE FROM schedules WHERE id = ?", (int(schedule_id),))


def run_schedule(schedule_id: int, *, triggered_by: str = "manual") -> dict:
    from nccm.backup.schedule_executor import execute_schedule

    return execute_schedule(schedule_id, triggered_by=triggered_by)


_watcher_started = False
_watcher_lock = threading.Lock()


def _due(sch: Schedule, now_ts: float) -> bool:
    if not sch.enabled:
        return False
    if not sch.last_run_at:
        return True
    try:
        last = datetime.strptime(sch.last_run_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        elapsed = now_ts - last.timestamp()
        return elapsed >= sch.interval_days * 86400
    except ValueError:
        return True


def tick_schedules() -> list[dict]:
    from nccm.backup.schedule_executor import ScheduleLock, execute_schedule, poll_running_jobs

    out: list[dict] = []
    lock = ScheduleLock()
    if not lock.acquire():
        return out
    try:
        out.extend(poll_running_jobs())
        now_ts = time.time()
        for sch in list_schedules():
            if _due(sch, now_ts):
                out.append(execute_schedule(sch.id, triggered_by="watcher"))
    finally:
        lock.release()
    return out


def start_schedule_watcher(*, interval_sec: float = 60.0) -> None:
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
