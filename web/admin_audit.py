from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from nccm.auth import audit as audit_mod
from web.deps import require_admin

CtxFn = Callable[..., dict]


def build_admin_audit_router(templates: Jinja2Templates, ctx: CtxFn) -> APIRouter:
    router = APIRouter(prefix="/admin/audit", tags=["admin"])

    @router.get("", response_class=HTMLResponse)
    async def audit_page(
        request: Request,
        _admin: str = Depends(require_admin),
        event: str = "",
        limit: int = Query(200, ge=1, le=2000),
    ):
        rows = audit_mod.list_audit_events(limit=limit, event=event)
        return templates.TemplateResponse(
            request,
            "admin_audit.html",
            ctx(
                request,
                "admin_audit",
                events=rows,
                event_filter=event,
                limit=limit,
            ),
        )

    @router.get("/export.csv")
    async def audit_export(
        request: Request,
        _admin: str = Depends(require_admin),
        event: str = "",
        limit: int = Query(5000, ge=1, le=20000),
    ):
        body = audit_mod.export_audit_csv(limit=limit, event=event)
        return PlainTextResponse(
            body,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="nccm-audit.csv"',
            },
        )

    return router
