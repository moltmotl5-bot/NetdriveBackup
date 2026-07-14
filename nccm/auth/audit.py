from __future__ import annotations

import os
from datetime import datetime, timezone

from starlette.requests import Request


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client:
        return request.client.host[:64]
    return "unknown"


def audit_portal_login(request: Request, username: str, success: bool) -> None:
    log_path = os.getenv("NCCM_AUDIT_LOG", "nccm_auth.log")
    safe_user = (username or "").replace("\n", "").replace("\r", "")[:128]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ip = client_ip(request)
    line = (
        f"{ts} ip={ip} user={safe_user!r} event=portal_login success={success}\n"
    )
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass