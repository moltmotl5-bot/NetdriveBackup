from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

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


def load_portal_credentials() -> tuple[str, str]:
    user = (os.getenv("NCCM_ADMIN_USER") or "").strip()
    password = os.getenv("NCCM_ADMIN_PASS") or ""
    if not user:
        raise RuntimeError("Missing NCCM_ADMIN_USER")
    if not password or len(password) < 12:
        raise RuntimeError("NCCM_ADMIN_PASS must be at least 12 characters")
    if password in _WEAK or password == user:
        raise RuntimeError("NCCM_ADMIN_PASS failed policy check")
    return user, password


def verify_login(username: str, password: str, valid_user: str, valid_pass: str) -> bool:
    return username == valid_user and password == valid_pass