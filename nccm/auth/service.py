from __future__ import annotations

import os
from typing import Literal

from nccm.auth import db as auth_db
from nccm.auth.passwords import (
    assert_password_policy,
    hash_password,
    password_policy_errors,
    verify_password,
)

Role = Literal["admin", "viewer"]


def user_count() -> int:
    with auth_db.connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM portal_users").fetchone()
        return int(row["c"]) if row else 0


def list_users() -> list[auth_db.PortalUser]:
    with auth_db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM portal_users ORDER BY username COLLATE NOCASE"
        ).fetchall()
        return [auth_db._row_to_user(r) for r in rows]


def get_user_by_username(username: str) -> auth_db.PortalUser | None:
    name = (username or "").strip()
    if not name:
        return None
    with auth_db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM portal_users WHERE username = ? COLLATE NOCASE",
            (name,),
        ).fetchone()
        return auth_db._row_to_user(row) if row else None


def get_user_by_id(user_id: int) -> auth_db.PortalUser | None:
    with auth_db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM portal_users WHERE id = ?", (int(user_id),)
        ).fetchone()
        return auth_db._row_to_user(row) if row else None


def create_user(username: str, password: str, role: Role = "viewer") -> auth_db.PortalUser:
    name = (username or "").strip()
    if not name:
        raise ValueError("username required")
    if role not in ("admin", "viewer"):
        raise ValueError("invalid role")
    assert_password_policy(name, password)
    now = auth_db._utc_now()
    ph = hash_password(password)
    with auth_db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO portal_users (username, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (name, ph, role, now, now),
        )
        uid = int(cur.lastrowid)
        row = conn.execute("SELECT * FROM portal_users WHERE id = ?", (uid,)).fetchone()
        return auth_db._row_to_user(row)


def set_password(user_id: int, new_password: str) -> None:
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("user not found")
    assert_password_policy(user.username, new_password)
    now = auth_db._utc_now()
    ph = hash_password(new_password)
    with auth_db.connect() as conn:
        conn.execute(
            "UPDATE portal_users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (ph, now, int(user_id)),
        )


def set_active(user_id: int, active: bool) -> None:
    if not active:
        _ensure_not_last_active_admin(user_id)
    now = auth_db._utc_now()
    with auth_db.connect() as conn:
        conn.execute(
            "UPDATE portal_users SET is_active = ?, updated_at = ? WHERE id = ?",
            (1 if active else 0, now, int(user_id)),
        )


def set_role(user_id: int, role: Role) -> None:
    if role not in ("admin", "viewer"):
        raise ValueError("invalid role")
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("user not found")
    if user.role == "admin" and role == "viewer":
        _ensure_not_last_active_admin(user_id)
    now = auth_db._utc_now()
    with auth_db.connect() as conn:
        conn.execute(
            "UPDATE portal_users SET role = ?, updated_at = ? WHERE id = ?",
            (role, now, int(user_id)),
        )


def _active_admin_count(exclude_id: int | None = None) -> int:
    with auth_db.connect() as conn:
        if exclude_id is None:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM portal_users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c FROM portal_users
                WHERE role = 'admin' AND is_active = 1 AND id != ?
                """,
                (int(exclude_id),),
            ).fetchone()
        return int(row["c"]) if row else 0


def _ensure_not_last_active_admin(user_id: int) -> None:
    user = get_user_by_id(user_id)
    if not user or user.role != "admin" or not user.is_active:
        return
    if _active_admin_count(exclude_id=user_id) < 1:
        raise ValueError("不可停用或降級最後一位啟用中的管理員")


def _load_env_bootstrap_credentials() -> tuple[str, str] | None:
    user = (os.getenv("NCCM_ADMIN_USER") or os.getenv("NCCM_BOOTSTRAP_USER") or "").strip()
    password = os.getenv("NCCM_ADMIN_PASS") or os.getenv("NCCM_BOOTSTRAP_PASS") or ""
    if not user or not password:
        return None
    if password_policy_errors(user, password):
        return None
    return user, password


def _verify_env_login(username: str, password: str) -> bool:
    creds = _load_env_bootstrap_credentials()
    if not creds:
        return False
    env_user, env_pass = creds
    return username == env_user and password == env_pass


def _import_env_user_to_db(username: str, password: str) -> auth_db.PortalUser:
    existing = get_user_by_username(username)
    if existing:
        return existing
    return create_user(username, password, role="admin")


def authenticate(username: str, password: str) -> auth_db.PortalUser | None:
    name = (username or "").strip()
    if not name:
        return None

    user = get_user_by_username(name)
    if user:
        if not user.is_active:
            return None
        with auth_db.connect() as conn:
            row = conn.execute(
                "SELECT password_hash FROM portal_users WHERE id = ?", (user.id,)
            ).fetchone()
        if row and verify_password(password, str(row["password_hash"])):
            _touch_last_login(user.id)
            return get_user_by_id(user.id)
        return None

    if user_count() == 0 and _verify_env_login(name, password):
        u = _import_env_user_to_db(name, password)
        _touch_last_login(u.id)
        return get_user_by_id(u.id)

    if _verify_env_login(name, password):
        return auth_db.PortalUser(
            id=0,
            username=name,
            role="admin",
            is_active=True,
            created_at="",
            updated_at="",
            last_login_at=None,
        )

    return None


def _touch_last_login(user_id: int) -> None:
    now = auth_db._utc_now()
    with auth_db.connect() as conn:
        conn.execute(
            "UPDATE portal_users SET last_login_at = ?, updated_at = ? WHERE id = ?",
            (now, now, int(user_id)),
        )


def ensure_portal_can_start() -> None:
    """Startup: init DB; require env bootstrap only when DB has no users."""
    auth_db.init_auth_db()
    if user_count() > 0:
        return
    creds = _load_env_bootstrap_credentials()
    if creds:
        return
    raise RuntimeError(
        "No portal users in DB and no valid NCCM_ADMIN_USER/NCCM_ADMIN_PASS bootstrap credentials"
    )