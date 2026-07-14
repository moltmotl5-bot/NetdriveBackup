from __future__ import annotations

from typing import List, Optional

from fastapi import Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from nccm.auth import api_tokens as token_service
from nccm.auth.audit import audit_api_token_event
from nccm.storage.index_db import InventoryDisplayRow, list_inventory_display

from fastapi import APIRouter

router = APIRouter(tags=["API"])

INVENTORY_SCOPE = "inventory:read"


def _get_api_auth(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> token_service.ApiAuthResult:
    if not token_service.any_api_auth_configured():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API token not configured on server",
        )
    auth = token_service.authenticate_api_key(x_api_key)
    if auth is None:
        audit_api_token_event(
            request,
            event="api_request",
            token_name="",
            success=False,
            detail="invalid_or_missing_key",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    if not token_service.token_has_scope(auth, INVENTORY_SCOPE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient API token scope",
        )
    audit_api_token_event(
        request,
        event="api_request",
        token_name=auth.token_name,
        success=True,
        detail=f"source={auth.source}",
    )
    return auth


@router.get("/inventory", response_model=List[dict])
async def get_inventory(
    request: Request,
    _auth: token_service.ApiAuthResult = Depends(_get_api_auth),
    site: Optional[str] = Query(None, description="Filter by site"),
    vendor: Optional[str] = Query(None, description="Filter by vendor"),
    q: Optional[str] = Query(None, description="Free text search (IP, hostname, model, serial)"),
    limit: int = Query(100, ge=1, le=500, description="Maximum number of rows to return"),
    offset: int = Query(0, ge=0, description="Number of rows to skip"),
) -> List[dict]:
    """
    Return a list of inventory items (expanded stack/HA members) as JSON.
    """
    rows: List[InventoryDisplayRow] = await run_in_threadpool(
        lambda: list_inventory_display(
            query=q or "",
            site=site or "",
            vendor=vendor or "",
            limit=limit + offset,
        )
    )
    sliced = rows[offset : offset + limit]

    result: List[dict] = []
    for r in sliced:
        item = {
            "device_id": r.device_id,
            "site": r.site,
            "ip": r.ip,
            "port": r.port,
            "hostname": r.hostname,
            "vendor": r.vendor,
            "sw_version": r.sw_version,
            "model_summary": r.model_summary,
            "serial_summary": r.serial_summary,
            "snapshot_count": r.snapshot_count,
            "stack_switch": r.stack_switch,
            "stack_role": r.stack_role,
            "is_config_anchor": r.is_config_anchor,
            "cluster_type": r.cluster_type,
        }
        result.append(item)
    return result


@router.get("/health")
async def api_health():
    return {"status": "ok"}