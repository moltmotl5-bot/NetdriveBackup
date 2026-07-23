from __future__ import annotations

import logging
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from nccm.auth import db as auth_db
from nccm.auth.passwords import hash_password, verify_password

_log = logging.getLogger(__name__)

DEFAULT_SCOPES = "inventory:read"
DEFAULT_TOKEN_TTL_DAYS = 90
MAX_TOKEN_TTL_DAYS = 365
MIN_TOKEN_TTL_DAYS = 1
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

    @property
    def is_expired(self) -> bool:
        return token_is_expired(self.expires_at)


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


def _parse_iso_utc(ts: str | None) -> datetime | None:
    if not ts or not str(ts).strip():
        return None
    s = str(ts).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def token_is_expired(expires_at: str | None, *, now: datetime | None = None) -> bool:
    """Missing expires_at is treated as expired (must re-issue with TTL)."""
    exp = _parse_iso_utc(expires_at)
    if exp is None:
        return True
    n = now or datetime.now(timezone.utc)
    return n >= exp


def normalize_ttl_days(days: int | None) -> int:
    if days is None:
        return DEFAULT_TOKEN_TTL_DAYS
    d = int(days)
    if d < MIN_TOKEN_TTL_DAYS:
        raise ValueError(f"有效期至少 {MIN_TOKEN_TTL_DAYS} 天")
    if d > MAX_TOKEN_TTL_DAYS:
        raise ValueError(f"有效期最多 {MAX_TOKEN_TTL_DAYS} 天")
    return d


def compute_expires_at(*, days: int | None = None, now: datetime | None = None) -> str:
    d = normalize_ttl_days(days)
    n = now or datetime.now(timezone.utc)
    exp = n + timedelta(days=d)
    return exp.strftime("%Y-%m-%dT%H:%M:%SZ")


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
    """Active and not expired tokens (usable for API)."""
    with auth_db.connect() as conn:
        rows = conn.execute(
            "SELECT expires_at FROM api_tokens WHERE is_active = 1"
        ).fetchall()
    n = 0
    for r in rows:
        if not token_is_expired(r["expires_at"]):
            n += 1
    return n


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
    expires_days: int | None = None,
) -> tuple[ApiToken, str]:
    label = (name or "").strip()
    if not label:
        raise ValueError("請輸入 token 名稱")
    if len(label) > 128:
        raise ValueError("名稱過長")
    expires_at = compute_expires_at(days=expires_days)
    plain, prefix = generate_plain_token()
    now = auth_db._utc_now()
    th = hash_api_token(plain)
    with auth_db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO api_tokens (
                name, token_prefix, token_hash, scopes, is_active,
                created_at, created_by, last_used_at, expires_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?, NULL, ?)
            """,
            (
                label,
                prefix,
                th,
                scopes.strip() or DEFAULT_SCOPES,
                now,
                created_by,
                expires_at,
            ),
        )
        tid = int(cur.lastrowid)
        row = conn.execute("SELECT * FROM api_tokens WHERE id = ?", (tid,)).fetchone()
    if not row:
        raise ValueError("create failed")
    return _row_to_token(row), plain


def set_token_active(token_id: int, active: bool) -> None:
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


def _verify_db_token(presented: str) -> tuple[ApiToken | None, str]:
    """Returns (token, fail_reason). fail_reason empty on success."""
    if len(presented) < _TOKEN_PREFIX_LEN:
        return None, "invalid_or_missing_key"
    prefix = presented[:_TOKEN_PREFIX_LEN]
    with auth_db.connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM api_tokens
            WHERE is_active = 1 AND token_prefix = ?
            """,
            (prefix,),
        ).fetchall()
    matched: ApiToken | None = None
    for row in rows:
        if verify_api_token(presented, str(row["token_hash"])):
            matched = _row_to_token(row)
            break
    if not matched:
        return None, "invalid_or_missing_key"
    if matched.is_expired:
        return None, "token_expired"
    _touch_last_used(matched.id)
    return matched, ""


def any_api_auth_configured() -> bool:
    return active_token_count() > 0


def authenticate_api_key(presented: str | None) -> ApiAuthResult | None:
    raw = (presented or "").strip()
    if not raw:
        return None
    tok, reason = _verify_db_token(raw)
    if tok:
        return ApiAuthResult(
            source="db",
            token_id=tok.id,
            token_name=tok.name,
            scopes=_parse_scopes(tok.scopes),
        )
    # Attach reason for callers via attribute on None is impossible;
    # use last_auth_failure module state for detail (simple).
    global _last_auth_failure
    _last_auth_failure = reason or "invalid_or_missing_key"
    return None


_last_auth_failure: str = "invalid_or_missing_key"


def last_auth_failure_reason() -> str:
    return _last_auth_failure


def token_has_scope(auth: ApiAuthResult, scope: str) -> bool:
    return scope in auth.scopes
