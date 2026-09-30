#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HMAC authentication middleware for Agent API endpoints."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

HEADER_TIMESTAMP = "X-NCCM-Timestamp"
HEADER_NONCE = "X-NCCM-Nonce"
HEADER_SIGNATURE = "X-NCCM-Signature"

MAX_SKEW_SECONDS = 120
_NONCE_TTL = MAX_SKEW_SECONDS * 2
_seen_nonces: dict[str, float] = {}


def _secret() -> str:
    return (os.environ.get("NCCM_AGENT_HMAC_SECRET") or "").strip()


def _auth_disabled() -> bool:
    return os.environ.get("NETDRIVER_AGENT_AUTH_DISABLED", "").strip() == "1"


def _purge_nonces(now: float) -> None:
    expired = [k for k, exp in _seen_nonces.items() if exp <= now]
    for k in expired:
        _seen_nonces.pop(k, None)


def _verify_signature(
    *,
    secret: str,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body: bytes,
    signature: str,
) -> str | None:
    try:
        ts = int(timestamp)
    except ValueError:
        return "invalid timestamp"
    now = int(time.time())
    if abs(now - ts) > MAX_SKEW_SECONDS:
        return "timestamp out of range"
    _purge_nonces(time.time())
    if nonce in _seen_nonces:
        return "nonce replay"
    body_sha = hashlib.sha256(body or b"").hexdigest()
    canonical = f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_sha}"
    expected = hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        return "invalid signature"
    _seen_nonces[nonce] = time.time() + _NONCE_TTL
    return None


class HmacAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if not path.startswith("/api/v1/") or request.method != "POST":
            return await call_next(request)

        secret = _secret()
        if not secret:
            if _auth_disabled():
                return await call_next(request)
            return JSONResponse(
                {"detail": "agent HMAC secret not configured"},
                status_code=503,
            )

        ts = request.headers.get(HEADER_TIMESTAMP, "")
        nonce = request.headers.get(HEADER_NONCE, "")
        sig = request.headers.get(HEADER_SIGNATURE, "")
        if not ts or not nonce or not sig:
            return JSONResponse({"detail": "missing HMAC headers"}, status_code=401)

        body = await request.body()

        async def receive() -> dict:
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = receive  # type: ignore[method-assign]

        err = _verify_signature(
            secret=secret,
            method=request.method,
            path=path,
            timestamp=ts,
            nonce=nonce,
            body=body,
            signature=sig,
        )
        if err:
            return JSONResponse({"detail": err}, status_code=401)

        return await call_next(request)
