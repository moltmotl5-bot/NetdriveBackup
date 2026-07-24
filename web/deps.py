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


def set_session_user(
    request: Request,
    *,
    username: str,
    role: str,
    user_id: int,
    must_change_password: bool = False,
) -> None:
    request.session["user"] = username
    request.session["role"] = role
    request.session["uid"] = int(user_id)
    request.session["must_change_password"] = bool(must_change_password)


def session_must_change_password(request: Request) -> bool:
    return bool(request.session.get("must_change_password"))


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
    """Admin or operator — blocks viewer from backup/rebuild/download/destructive ops."""
    name = require_user(request)
    if session_role(request) not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="forbidden")
    return name


def current_user(request: Request) -> str:
    return session_username(request)


def role_can_operate(role: str) -> bool:
    return (role or "") in ("admin", "operator")


def role_can_view_schedules(role: str) -> bool:
    return (role or "") in ("admin", "operator", "viewer")
