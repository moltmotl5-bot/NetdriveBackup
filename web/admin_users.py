from __future__ import annotations

from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from nccm.auth import service as auth_service
from web.deps import require_admin, session_user_id

CtxFn = Callable[..., dict]


def build_admin_users_router(templates: Jinja2Templates, ctx: CtxFn) -> APIRouter:
    router = APIRouter(prefix="/admin/users", tags=["admin"])

    @router.get("", response_class=HTMLResponse)
    async def admin_users_page(request: Request, _admin: str = Depends(require_admin)):
        return templates.TemplateResponse(
            request,
            "admin_users.html",
            ctx(request, "admin_users", users=auth_service.list_users(), error=None, message=None),
        )

    @router.get("/partial/table", response_class=HTMLResponse)
    async def admin_users_table(request: Request, _admin: str = Depends(require_admin)):
        return templates.TemplateResponse(
            request,
            "partials/admin_users_table.html",
            {
                "request": request,
                "users": auth_service.list_users(),
                "current_uid": session_user_id(request),
            },
        )

    def _page(request: Request, *, error: str | None, message: str | None):
        return templates.TemplateResponse(
            request,
            "admin_users.html",
            ctx(
                request,
                "admin_users",
                users=auth_service.list_users(),
                error=error,
                message=message,
            ),
        )

    @router.post("", response_class=HTMLResponse)
    async def admin_users_create(
        request: Request,
        _admin: str = Depends(require_admin),
        username: Annotated[str, Form()] = "",
        password: Annotated[str, Form()] = "",
        role: Annotated[str, Form()] = "viewer",
    ):
        try:
            r = role if role in ("admin", "viewer") else "viewer"
            auth_service.create_user(username, password, role=r)  # type: ignore[arg-type]
            return _page(request, error=None, message="已新增使用者")
        except ValueError as e:
            return _page(request, error=str(e), message=None)

    @router.post("/{user_id}/password", response_class=HTMLResponse)
    async def admin_users_password(
        request: Request,
        user_id: int,
        _admin: str = Depends(require_admin),
        new_password: Annotated[str, Form()] = "",
    ):
        try:
            auth_service.set_password(user_id, new_password)
            return _page(request, error=None, message="已更新密碼")
        except ValueError as e:
            return _page(request, error=str(e), message=None)

    @router.post("/{user_id}/toggle", response_class=HTMLResponse)
    async def admin_users_toggle(
        request: Request,
        user_id: int,
        _admin: str = Depends(require_admin),
    ):
        user = auth_service.get_user_by_id(user_id)
        if not user:
            raise HTTPException(404)
        try:
            auth_service.set_active(user_id, not user.is_active)
            return _page(request, error=None, message="已更新狀態")
        except ValueError as e:
            return _page(request, error=str(e), message=None)

    @router.post("/{user_id}/role", response_class=HTMLResponse)
    async def admin_users_role(
        request: Request,
        user_id: int,
        _admin: str = Depends(require_admin),
        role: Annotated[str, Form()] = "viewer",
    ):
        try:
            r = role if role in ("admin", "viewer") else "viewer"
            auth_service.set_role(user_id, role=r)  # type: ignore[arg-type]
            return _page(request, error=None, message="已更新角色")
        except ValueError as e:
            return _page(request, error=str(e), message=None)

    return router