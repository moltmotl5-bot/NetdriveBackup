"""HMAC request signing for Portal → NetDriver Agent API calls."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from typing import Any

HEADER_TIMESTAMP = "X-NCCM-Timestamp"
HEADER_NONCE = "X-NCCM-Nonce"
HEADER_SIGNATURE = "X-NCCM-Signature"


def agent_hmac_secret() -> str:
    return (os.environ.get("NCCM_AGENT_HMAC_SECRET") or "").strip()


def _body_bytes(body: Any) -> bytes:
    if body is None:
        return b""
    if isinstance(body, bytes):
        return body
    return json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sign_request(*, method: str, path: str, body: Any = None) -> dict[str, str]:
    secret = agent_hmac_secret()
    if not secret:
        raise RuntimeError("NCCM_AGENT_HMAC_SECRET is not configured")
    ts = str(int(time.time()))
    nonce = str(uuid.uuid4())
    body_sha = hashlib.sha256(_body_bytes(body)).hexdigest()
    canonical = f"{method.upper()}\n{path}\n{ts}\n{nonce}\n{body_sha}"
    sig = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        HEADER_TIMESTAMP: ts,
        HEADER_NONCE: nonce,
        HEADER_SIGNATURE: sig,
    }


def signed_post(url: str, *, path: str, body: dict[str, Any], timeout: float) -> Any:
    """POST JSON with HMAC headers; returns httpx Response."""
    import httpx

    headers = sign_request(method="POST", path=path, body=body)
    headers["Content-Type"] = "application/json"
    payload = _body_bytes(body)
    return httpx.post(url, content=payload, headers=headers, timeout=timeout)
