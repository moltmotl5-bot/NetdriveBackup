#!/usr/bin/env python3
"""Web smoke test for NCCM v3 (login + main pages). Requires deps from requirements-v3.txt."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("NCCM_NETDRIVER_URL", "http://127.0.0.1:8000")
os.environ.setdefault("NCCM_STORE_DIR", str(ROOT / "store"))


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)

    if not os.environ.get("NCCM_ADMIN_USER"):
        os.environ["NCCM_ADMIN_USER"] = "smoke_test_admin"
    if not os.environ.get("NCCM_ADMIN_PASS"):
        os.environ["NCCM_ADMIN_PASS"] = "smoke_test_pass_12chars"

    user = os.environ["NCCM_ADMIN_USER"]
    password = os.environ["NCCM_ADMIN_PASS"]

    from starlette.testclient import TestClient

    from web.main import app

    failures: list[str] = []
    passed: list[str] = []

    with TestClient(app) as client:
        r = client.get("/login")
        if r.status_code == 200:
            passed.append("GET /login")
        else:
            failures.append(f"GET /login -> {r.status_code}")

        r = client.post(
            "/login",
            data={"username": user, "password": password},
            follow_redirects=False,
        )
        if r.status_code in (303, 302):
            passed.append("POST /login")
        else:
            failures.append(f"POST /login -> {r.status_code} ({r.text[:120]})")

        for path in ("/backup", "/inventory", "/neighbors", "/interfaces"):
            r = client.get(path)
            if r.status_code == 200:
                passed.append(f"GET {path}")
            else:
                failures.append(f"GET {path} -> {r.status_code}")

        r = client.get("/backup/events/00000000-0000-0000-0000-000000000000")
        ctype = r.headers.get("content-type", "")
        if r.status_code == 200 and "text/event-stream" in ctype and "data:" in r.text:
            passed.append("GET /backup/events (sse)")
        elif r.status_code in (302, 303):
            failures.append("SSE route redirect (auth)")
        else:
            failures.append(f"SSE route -> {r.status_code} ctype={ctype}")

    print(json.dumps({"pass": passed, "fail": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())