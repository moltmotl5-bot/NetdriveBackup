from __future__ import annotations

import hashlib
import secrets

_WEAK = frozenset(
    {
        "NCCM@2026",
        "password",
        "changeme",
        "admin",
        "your_admin_password",
        "REPLACE_WITH_12CHAR_MIN",
    }
)

_ITERATIONS = 600_000


def password_policy_errors(username: str, password: str) -> list[str]:
    errs: list[str] = []
    u = (username or "").strip()
    p = password or ""
    if len(p) < 12:
        errs.append("密碼至少 12 字元")
    if p == u:
        errs.append("密碼不可與帳號相同")
    if p in _WEAK:
        errs.append("密碼過於常見或為預設值")
    return errs


def assert_password_policy(username: str, password: str) -> None:
    errs = password_policy_errors(username, password)
    if errs:
        raise ValueError(errs[0])


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _ITERATIONS
    )
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt, hexdigest = stored.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    iters = int(iters_s)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iters
    )
    return secrets.compare_digest(digest.hex(), hexdigest)