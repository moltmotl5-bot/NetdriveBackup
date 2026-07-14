from __future__ import annotations

from typing import Annotated, Callable

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from nccm.auth import service as auth_service
from nccm.auth.passwords import password_policy_errors
from web.deps import (
    require_user,
    session_must_change_password,
    session_user_id,
    session_username,
    set_session_user,
)


def build_account_router(
    templates: Jinja2Templates, ctx: Callable[..., dict]
) -> APIRouter:
    router = APIRouter(tags=["account"])

    @router.get("/account/change-password", response_class=HTMLResponse)
    async def change_password_page(request: Request):
        if not session_username(request):
            return RedirectResponse("/login", status_code=303)
        if not session_must_change_password(request):
            return RedirectResponse("/inventory", status_code=303)
        return templates.TemplateResponse(
            request,
            "change_password.html",
            ctx(request, "change_password", force_minimal_nav=True),
        )

    @router.post("/account/change-password")
    async def change_password_submit(
        request: Request,
        current_password: Annotated[str, Form()],
        new_password: Annotated[str, Form()],
        confirm_password: Annotated[str, Form()],
    ):
        require_user(request)
        if not session_must_change_password(request):
            return RedirectResponse("/inventory", status_code=303)
        if new_password != confirm_password:
            return templates.TemplateResponse(
                request,
                "change_password.html",
                ctx(
                    request,
                    "change_password",
                    error="新密碼與確認不一致",
                    force_minimal_nav=True,
                ),
            )
        name = session_username(request)
        errs = password_policy_errors(name, new_password)
        if errs:
            return templates.TemplateResponse(
                request,
                "change_password.html",
                ctx(
                    request,
                    "change_password",
                    error="；".join(errs),
                    force_minimal_nav=True,
                ),
            )
        try:
            uid = session_user_id(request)
            if uid <= 0:
                user = auth_service.change_password_env_login(
                    name, current_password, new_password
                )
            else:
                user = auth_service.change_password_self(
                    uid, current_password, new_password
                )
        except ValueError as e:
            return templates.TemplateResponse(
                request,
                "change_password.html",
                ctx(
                    request,
                    "change_password",
                    error=str(e),
                    force_minimal_nav=True,
                ),
            )
        set_session_user(
            request,
            username=user.username,
            role=user.role,
            user_id=user.id,
            must_change_password=False,
        )
        dest = "/inventory" if user.role == "viewer" else "/backup"
        return RedirectResponse(dest, status_code=303)

    return router