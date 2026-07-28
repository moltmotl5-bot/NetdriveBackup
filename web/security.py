"""Web security configuration: session, production mode, response headers."""
from __future__ import annotations

import os
import secrets


def production_mode() -> bool:
    env = (os.environ.get("NCCM_ENV") or "").strip().lower()
    return env in {"production", "prod"} or os.environ.get("NCCM_PRODUCTION") == "1"


def https_only_cookies() -> bool:
    return os.environ.get("NCCM_HTTPS") == "1" or production_mode()


def session_secret() -> str:
    secret = (os.environ.get("NCCM_SESSION_SECRET") or "").strip()
    if secret:
        return secret
    if os.environ.get("NCCM_ALLOW_EPHEMERAL_SESSION") == "1":
        return secrets.token_hex(32)
    raise RuntimeError(
        "NCCM_SESSION_SECRET is required. Set a stable random value in .env "
        "(or NCCM_ALLOW_EPHEMERAL_SESSION=1 for local dev only)."
    )


def security_headers() -> dict[str, str]:
    csp = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'none'; "
        "form-action 'self'"
    )
    headers = {
        "Content-Security-Policy": csp,
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
    }
    if https_only_cookies():
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers
