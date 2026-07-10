from __future__ import annotations

import os
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from nccm.storage.index_db import InventoryDisplayRow, list_inventory_display

router = APIRouter(tags=["API"])


def _get_api_key(x_api_key: Optional[str] = Header(None)) -> str:
    expected = os.environ.get("API_KEY")
    if not expected:
        # If no API key is set, deny access by default (secure fail‑closed)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key not configured on server",
        )
    if x_api_key is None or x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return x_api_key or ""  # return the valid key (not used further)


@router.get("/inventory", response_model=List[dict])
async def get_inventory(
    request: Request,
    api_key: str = Depends(_get_api_key),
    site: Optional[str] = Query(None, description="Filter by site"),
    vendor: Optional[str] = Query(None, description="Filter by vendor"),
    q: Optional[str] = Query(None, description="Free text search (IP, hostname, model, serial)"),
    limit: int = Query(100, ge=1, le=500, description="Maximum number of rows to return"),
    offset: int = Query(0, ge=0, description="Number of rows to skip"),
) -> List[dict]:
    """
    Return a list of inventory items (expanded stack/HA members) as JSON.
    """
    # Run the synchronous DB call in a threadpool to avoid blocking the event loop
    rows: List[InventoryDisplayRow] = await run_in_threadpool(
        lambda: list_inventory_display(
            query=q or "",
            site=site or "",
            vendor=vendor or "",
            limit=limit + offset,  # fetch extra to allow slicing for offset
        )
    )
    # Apply offset manually (simple pagination)
    sliced = rows[offset : offset + limit]

    # Convert dataclasses to plain dicts for JSON serialization
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


# Optional: health check for API
@router.get("/health")
async def api_health():
    return {"status": "ok"}