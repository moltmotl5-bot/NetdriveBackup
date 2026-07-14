from __future__ import annotations

import logging
import os
import secrets
import time
from dataclasses import dataclass

from nccm.auth import db as auth_db
from nccm.auth.passwords import hash_password, verify_password

_log = logging.getLogger(__name__)

DEFAULT_SCOPES = "inventory:read"
_TOKEN_PREFIX_LEN = 8
_last_used_touch: dict[int, float] = {}
_LAST_USED_INTERVAL_SEC = 300.0

Scope = str


@dataclass(frozen=True)
class ApiToken:
    id: int
    name: str
    token_prefix: str
    scopes: str
    is_active: bool
    created_at: str
    created_by: str | None
    last_used_at: str | None
    expires_at: str | None


@dataclass(frozen=True)
class ApiAuthResult:
    """Successful API authentication."""

    source: str  # "db"
    token_id: int
    token_name: str
    scopes: frozenset[str]


def _pepper() -> str:
    return os.environ.get("NCCM_API_TOKEN_PEPPER", "") or ""


def _hash_material(plain_token: str) -> str:
    return plain_token + _pepper()


def hash_api_token(plain_token: str) -> str:
    return hash_password(_hash_material(plain_token))


def verify_api_token(plain_token: str, stored_hash: str) -> bool:
    return verify_password(_hash_material(plain_token), stored_hash)


def _row_to_token(row) -> ApiToken:
    return ApiToken(
        id=int(row["id"]),
        name=str(row["name"]),
        token_prefix=str(row["token_prefix"]),
        scopes=str(row["scopes"] or DEFAULT_SCOPES),
        is_active=bool(row["is_active"]),
        created_at=str(row["created_at"]),
        created_by=row["created_by"],
        last_used_at=row["last_used_at"],
        expires_at=row["expires_at"],
    )


def _parse_scopes(scopes: str) -> frozenset[str]:
    parts = [s.strip() for s in (scopes or "").split(",") if s.strip()]
    return frozenset(parts or [DEFAULT_SCOPES])


def generate_plain_token() -> tuple[str, str]:
    plain = "nccm_" + secrets.token_urlsafe(32)
    return plain, plain[:_TOKEN_PREFIX_LEN]


def active_token_count() -> int:
    with auth_db.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM api_tokens WHERE is_active = 1"
        ).fetchone()
    return int(row["c"]) if row else 0


def list_tokens() -> list[ApiToken]:
    with auth_db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM api_tokens ORDER BY id ASC"
        ).fetchall()
    return [_row_to_token(r) for r in rows]


def create_token(
    name: str,
    *,
    scopes: str = DEFAULT_SCOPES,
    created_by: str | None = None,
) -> tuple[ApiToken, str]:
    label = (name or "").strip()
    if not label:
        raise ValueError("請輸入 token 名稱")
    if len(label) > 128:
        raise ValueError("名稱過長")
    plain, prefix = generate_plain_token()
    now = auth_db._utc_now()
    th = hash_api_token(plain)
    with auth_db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO api_tokens (
                name, token_prefix, token_hash, scopes, is_active,
                created_at, created_by, last_used_at, expires_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?, NULL, NULL)
            """,
            (label, prefix, th, scopes.strip() or DEFAULT_SCOPES, now, created_by),
        )
        tid = int(cur.lastrowid)
        row = conn.execute("SELECT * FROM api_tokens WHERE id = ?", (tid,)).fetchone()
    if not row:
        raise ValueError("create failed")
    return _row_to_token(row), plain


def set_token_active(token_id: int, active: bool) -> None:
    now = auth_db._utc_now()
    with auth_db.connect() as conn:
        conn.execute(
            "UPDATE api_tokens SET is_active = ? WHERE id = ?",
            (1 if active else 0, int(token_id)),
        )


def _touch_last_used(token_id: int) -> None:
    now_mono = time.monotonic()
    if now_mono - _last_used_touch.get(token_id, 0.0) < _LAST_USED_INTERVAL_SEC:
        return
    _last_used_touch[token_id] = now_mono
    ts = auth_db._utc_now()
    with auth_db.connect() as conn:
        conn.execute(
            "UPDATE api_tokens SET last_used_at = ? WHERE id = ?",
            (ts, int(token_id)),
        )


def _verify_db_token(presented: str) -> ApiToken | None:
    if len(presented) < _TOKEN_PREFIX_LEN:
        return None
    prefix = presented[:_TOKEN_PREFIX_LEN]
    with auth_db.connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM api_tokens
            WHERE is_active = 1 AND token_prefix = ?
            """,
            (prefix,),
        ).fetchall()
    for row in rows:
        if verify_api_token(presented, str(row["token_hash"])):
            tok = _row_to_token(row)
            _touch_last_used(tok.id)
            return tok
    return None


def any_api_auth_configured() -> bool:
    return active_token_count() > 0


def authenticate_api_key(presented: str | None) -> ApiAuthResult | None:
    raw = (presented or "").strip()
    if not raw:
        return None

    tok = _verify_db_token(raw)
    if tok:
        return ApiAuthResult(
            source="db",
            token_id=tok.id,
            token_name=tok.name,
            scopes=_parse_scopes(tok.scopes),
        )
    return None


def token_has_scope(auth: ApiAuthResult, scope: str) -> bool:
    return scope in auth.scopes