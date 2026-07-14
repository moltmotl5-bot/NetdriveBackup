from __future__ import annotations

from fastapi import HTTPException, Request


def session_username(request: Request) -> str:
    return str(request.session.get("user") or "")


def session_role(request: Request) -> str:
    return str(request.session.get("role") or "")


def session_user_id(request: Request) -> int:
    try:
        return int(request.session.get("uid") or 0)
    except (TypeError, ValueError):
        return 0


def set_session_user(request: Request, *, username: str, role: str, user_id: int) -> None:
    request.session["user"] = username
    request.session["role"] = role
    request.session["uid"] = int(user_id)


def require_user(request: Request) -> str:
    name = session_username(request)
    if not name:
        raise HTTPException(status_code=401, detail="login required")
    return name


def require_admin(request: Request) -> str:
    name = require_user(request)
    if session_role(request) != "admin":
        raise HTTPException(status_code=403, detail="admin required")
    return name


def require_operator(request: Request) -> str:
    """Admin only — blocks viewer from backup/rebuild/download/admin."""
    name = require_user(request)
    if session_role(request) != "admin":
        raise HTTPException(status_code=403, detail="forbidden")
    return name


def current_user(request: Request) -> str:
    return session_username(request)