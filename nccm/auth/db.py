from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from nccm.config import auth_db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS portal_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT,
    must_change_password INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_portal_users_active ON portal_users(is_active);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class PortalUser:
    id: int
    username: str
    role: str
    is_active: bool
    created_at: str
    updated_at: str
    last_login_at: str | None
    must_change_password: bool = False


def _migrate_portal_users(conn: sqlite3.Connection) -> None:
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(portal_users)")}
    if "must_change_password" not in cols:
        conn.execute(
            "ALTER TABLE portal_users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0"
        )


def init_auth_db() -> None:
    path = auth_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(_SCHEMA)
        _migrate_portal_users(conn)
        conn.commit()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    init_auth_db()
    conn = sqlite3.connect(auth_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_user(row: sqlite3.Row) -> PortalUser:
    return PortalUser(
        id=int(row["id"]),
        username=str(row["username"]),
        role=str(row["role"]),
        is_active=bool(row["is_active"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        last_login_at=row["last_login_at"],
        must_change_password=bool(row["must_change_password"] if "must_change_password" in row.keys() else 0),
    )