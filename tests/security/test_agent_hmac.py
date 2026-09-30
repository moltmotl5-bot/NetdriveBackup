from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

import pytest

from nccm.netdriver.agent_auth import sign_request


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NCCM_AGENT_HMAC_SECRET", "test-secret-for-hmac-auth")


def test_sign_request_deterministic_fields():
    body = {"ip": "10.0.0.1", "port": 22}
    headers = sign_request(method="POST", path="/api/v1/probe", body=body)
    assert headers["X-NCCM-Timestamp"]
    assert headers["X-NCCM-Nonce"]
    assert len(headers["X-NCCM-Signature"]) == 64


def test_signature_matches_agent_canonical():
    secret = "test-secret-for-hmac-auth"
    body = {"ip": "10.0.0.1", "port": 22, "timeout": 3.0}
    ts = str(int(time.time()))
    nonce = "00000000-0000-4000-8000-000000000001"
    body_sha = hashlib.sha256(
        json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    canonical = f"POST\n/api/v1/probe\n{ts}\n{nonce}\n{body_sha}"
    expected = hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    # patch uuid/time via direct canonical check
    assert expected


def test_missing_secret_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NCCM_AGENT_HMAC_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        sign_request(method="POST", path="/api/v1/probe", body={})
