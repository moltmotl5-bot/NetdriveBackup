from __future__ import annotations

from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from nccm.auth import api_tokens as token_service
from nccm.auth.audit import audit_api_token_event
from web.deps import require_admin, session_username

CtxFn = Callable[..., dict]


def build_admin_api_tokens_router(templates: Jinja2Templates, ctx: CtxFn) -> APIRouter:
    router = APIRouter(prefix="/admin/api-tokens", tags=["admin"])

    def _page(
        request: Request,
        *,
        error: str | None,
        message: str | None,
        reveal_token: str | None = None,
    ):
        return templates.TemplateResponse(
            request,
            "admin_api_tokens.html",
            ctx(
                request,
                "admin_api_tokens",
                tokens=token_service.list_tokens(),
                error=error,
                message=message,
                reveal_token=reveal_token,
            ),
        )

    @router.get("", response_class=HTMLResponse)
    async def api_tokens_page(request: Request, _admin: str = Depends(require_admin)):
        reveal = request.session.pop("api_token_reveal", None)
        return _page(request, error=None, message=None, reveal_token=reveal)

    @router.post("", response_class=HTMLResponse)
    async def api_tokens_create(
        request: Request,
        _admin: str = Depends(require_admin),
        name: Annotated[str, Form()] = "",
        scopes: Annotated[str, Form()] = token_service.DEFAULT_SCOPES,
    ):
        try:
            tok, plain = token_service.create_token(
                name,
                scopes=scopes,
                created_by=session_username(request),
            )
            request.session["api_token_reveal"] = plain
            audit_api_token_event(
                request,
                event="api_token_created",
                token_name=tok.name,
                success=True,
            )
            return RedirectResponse("/admin/api-tokens", status_code=303)
        except ValueError as e:
            return _page(request, error=str(e), message=None)

    @router.post("/{token_id}/deactivate", response_class=HTMLResponse)
    async def api_tokens_deactivate(
        request: Request,
        token_id: int,
        _admin: str = Depends(require_admin),
    ):
        token_service.set_token_active(token_id, False)
        audit_api_token_event(
            request,
            event="api_token_revoked",
            token_name=f"id:{token_id}",
            success=True,
        )
        return _page(request, error=None, message="已停用 token")

    return router