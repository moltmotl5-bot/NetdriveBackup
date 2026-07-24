"""Scheduled backup jobs: CSV list + dry/mock or live (credentials encrypted at rest)."""
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
from nccm.registry.csv import load_devices_csv

MODE_DRY_MOCK = "dry_mock"
MODE_LIVE = "live"
VALID_MODES = frozenset({MODE_DRY_MOCK, MODE_LIVE})


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def schedules_db_path() -> Path:
    return store_dir() / "schedules.db"


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
            every_minutes INTEGER NOT NULL DEFAULT 60,
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
        ("mode", "TEXT NOT NULL DEFAULT 'dry_mock'"),
        ("username", "TEXT NOT NULL DEFAULT ''"),
        ("password_enc", "TEXT NOT NULL DEFAULT ''"),
        ("enable_password_enc", "TEXT NOT NULL DEFAULT ''"),
        ("running_job_id", "TEXT NOT NULL DEFAULT ''"),
        ("last_job_id", "TEXT NOT NULL DEFAULT ''"),
        ("last_ok_count", "INTEGER NOT NULL DEFAULT 0"),
        ("last_fail_count", "INTEGER NOT NULL DEFAULT 0"),
        ("created_by", "TEXT NOT NULL DEFAULT ''"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE schedules ADD COLUMN {name} {ddl}")
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
    every_minutes: int
    enabled: bool
    mode: str
    username: str
    password_set: bool
    enable_password_set: bool
    last_run_at: str
    last_result: str
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


def _row(r: sqlite3.Row) -> Schedule:
    password_enc = str(r["password_enc"] or "")
    enable_enc = str(r["enable_password_enc"] or "")
    mode = str(r["mode"] or MODE_DRY_MOCK)
    if mode not in VALID_MODES:
        mode = MODE_DRY_MOCK
    return Schedule(
        id=int(r["id"]),
        name=str(r["name"]),
        csv_text=str(r["csv_text"] or ""),
        every_minutes=int(r["every_minutes"] or 60),
        enabled=bool(r["enabled"]),
        mode=mode,
        username=str(r["username"] or ""),
        password_set=bool(password_enc.strip()),
        enable_password_set=bool(enable_enc.strip()),
        last_run_at=str(r["last_run_at"] or ""),
        last_result=str(r["last_result"] or ""),
        created_by=str(r["created_by"] or ""),
    )


def _normalize_mode(mode: str) -> str:
    m = (mode or MODE_DRY_MOCK).strip().lower()
    if m in ("dry-mock", "dry_mock", "mock"):
        return MODE_DRY_MOCK
    if m in ("live", "real"):
        return MODE_LIVE
    return MODE_DRY_MOCK


def _validate_live_fields(*, username: str, password_enc: str, password_plain: str | None) -> None:
    user = (username or "").strip()
    has_password = bool((password_enc or "").strip()) or bool(password_plain)
    if not user or not has_password:
        raise ValueError("live 模式需要 SSH 帳號與密碼")


def _prepare_live_storage(
    *,
    username: str,
    password: str,
    enable_password: str,
    password_enc: str = "",
    enable_enc: str = "",
) -> tuple[str, str, str, KeyEnsureResult | None]:
    _validate_live_fields(
        username=username,
        password_enc=password_enc,
        password_plain=password or None,
    )
    key_result: KeyEnsureResult | None = None
    needs_key = bool(password) or bool(enable_password) or not secrets_configured()
    if needs_key:
        try:
            key_result = ensure_master_key()
        except SecretsKeyWriteError as exc:
            raise ValueError(str(exc)) from exc
    out_pass = encrypt(password) if password else password_enc
    out_enable = encrypt(enable_password) if enable_password else enable_enc
    return (username or "").strip(), out_pass, out_enable, key_result

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


def create_schedule(
    name: str,
    csv_text: str,
    *,
    every_minutes: int = 60,
    mode: str = MODE_DRY_MOCK,
    username: str = "",
    password: str = "",
    enable_password: str = "",
    created_by: str = "",
) -> ScheduleWriteResult:
    name = (name or "").strip() or "schedule"
    body = (csv_text or "").strip()
    if not body:
        raise ValueError("csv_text required")
    mock_run_csv(body)
    mins = max(1, int(every_minutes))
    mode_n = _normalize_mode(mode)
    key_result: KeyEnsureResult | None = None
    if mode_n == MODE_LIVE:
        user, password_enc, enable_enc, key_result = _prepare_live_storage(
            username=username,
            password=password,
            enable_password=enable_password,
        )
    else:
        if password or enable_password:
            raise ValueError("dry-mock 排程不可儲存 SSH 憑證；請選 live 模式")
        password_enc = ""
        enable_enc = ""
        user = ""
    now = _utc_now()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO schedules (
                name, csv_text, every_minutes, enabled, mode,
                username, password_enc, enable_password_enc,
                created_by, created_at, updated_at
            )
            VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                body,
                mins,
                mode_n,
                user,
                password_enc,
                enable_enc,
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
    every_minutes: int | None = None,
    mode: str | None = None,
    username: str | None = None,
    password: str | None = None,
    enable_password: str | None = None,
) -> ScheduleWriteResult:
    key_result: KeyEnsureResult | None = None
    with _connect() as conn:
        row = _get_schedule_row(conn, int(schedule_id))
        if not row:
            raise ValueError("schedule not found")

        new_name = (name if name is not None else str(row["name"])).strip() or "schedule"
        new_csv = (csv_text if csv_text is not None else str(row["csv_text"] or "")).strip()
        if not new_csv:
            raise ValueError("csv_text required")
        mock_run_csv(new_csv)

        new_mins = max(1, int(every_minutes if every_minutes is not None else row["every_minutes"]))
        new_mode = _normalize_mode(mode if mode is not None else str(row["mode"] or MODE_DRY_MOCK))
        new_user = (username if username is not None else str(row["username"] or "")).strip()

        password_enc = str(row["password_enc"] or "")
        enable_enc = str(row["enable_password_enc"] or "")

        if new_mode == MODE_LIVE:
            plain_pass = password if password is not None else ""
            plain_enable = enable_password if enable_password is not None else ""
            if password is not None or enable_password is not None or not secrets_configured():
                new_user, password_enc, enable_enc, key_result = _prepare_live_storage(
                    username=new_user,
                    password=plain_pass if password is not None else "",
                    enable_password=plain_enable if enable_password is not None else "",
                    password_enc=password_enc if password is None else "",
                    enable_enc=enable_enc if enable_password is None else "",
                )
            else:
                _validate_live_fields(
                    username=new_user,
                    password_enc=password_enc,
                    password_plain=None,
                )
        else:
            new_user = ""
            password_enc = ""
            enable_enc = ""

        now = _utc_now()
        conn.execute(
            """
            UPDATE schedules SET
                name = ?, csv_text = ?, every_minutes = ?, mode = ?,
                username = ?, password_enc = ?, enable_password_enc = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_name,
                new_csv,
                new_mins,
                new_mode,
                new_user,
                password_enc,
                enable_enc,
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
    """Decrypt stored credentials for backup execution (Phase B)."""
    with _connect() as conn:
        row = _get_schedule_row(conn, int(schedule_id))
        if not row:
            raise ValueError("schedule not found")
        if str(row["mode"] or MODE_DRY_MOCK) != MODE_LIVE:
            raise ValueError("schedule is not live mode")
        user = str(row["username"] or "").strip()
        password_enc = str(row["password_enc"] or "")
        enable_enc = str(row["enable_password_enc"] or "")
        _validate_live_fields(username=user, password_enc=password_enc, password_plain=None)
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
    if enabled and sch.mode == MODE_LIVE:
        if not secrets_configured():
            raise ValueError("加密主金鑰遺失或無法讀取，無法啟用 live 排程")
        if not sch.username.strip() or not sch.password_set:
            raise ValueError("live 排程缺少 SSH 帳密，無法啟用")
    with _connect() as conn:
        conn.execute(
            "UPDATE schedules SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, _utc_now(), int(schedule_id)),
        )


def delete_schedule(schedule_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM schedule_runs WHERE schedule_id = ?", (int(schedule_id),))
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
    if sch.mode == MODE_LIVE:
        return {
            "ok": False,
            "mode": MODE_LIVE,
            "schedule_id": schedule_id,
            "error": "live 執行尚未實作（Phase B）；請使用 dry-mock 或「立即 mock」",
            "message": "Phase B pending",
        }
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
        last = datetime.strptime(sch.last_run_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        elapsed = now_ts - last.timestamp()
        return elapsed >= sch.every_minutes * 60
    except ValueError:
        return True


def tick_schedules() -> list[dict]:
    """Run all due schedules (mock for dry_mock; live skipped until Phase B)."""
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
