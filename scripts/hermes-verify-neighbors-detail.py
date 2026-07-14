#!/usr/bin/env python3
"""Ad-hoc verify neighbors detail partial (delete after use)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault("NCCM_ADMIN_USER", "admin")
os.environ.setdefault("NCCM_ADMIN_PASS", "password123456")
os.environ.setdefault("NCCM_SESSION_SECRET", "testsecret")

from fastapi.testclient import TestClient
from web.main import app

client = TestClient(app)
client.post(
    "/login",
    data={"username": "admin", "password": "password123456"},
    follow_redirects=False,
)
device_key = "MUSEA|10.11.246.213|DS-SW-B2A-1A"
resp = client.get("/neighbors/partial/detail", params={"device_key": device_key})
print("Status:", resp.status_code)
if resp.status_code != 200:
    print(resp.text[:800])
    sys.exit(1)
print("=== hermes-verify neighbors detail partial PASSED ===")