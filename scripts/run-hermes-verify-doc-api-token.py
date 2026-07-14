#!/usr/bin/env python3
"""Ad-hoc: README + Handbook + API Token page manual (doc consistency)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
readme = (ROOT / "README.md").read_text(encoding="utf-8")
handbook = (ROOT / "docs/Handbook.html").read_text(encoding="utf-8")
env_ex = (ROOT / ".env.example").read_text(encoding="utf-8")
admin = (ROOT / "web/templates/admin_api_tokens.html").read_text(encoding="utf-8")
manual = (ROOT / "web/templates/partials/api_token_manual.html").read_text(encoding="utf-8")

for line in env_ex.splitlines():
    stripped = line.strip()
    if stripped.startswith("API_KEY="):
        raise AssertionError(".env.example must not define API_KEY")

for needle in ("API Token", "portal_auth.db", "inventory:read"):
    assert needle in readme, f"README missing {needle}"
assert "REST API（API Token）" in handbook
assert "不在" in handbook and ".env" in handbook
assert "api_token_manual.html" in admin
assert "REST API 使用手冊" in manual and "/api/v1/inventory" in manual
print("doc consistency: OK")
print("=== ad-hoc doc-api-token verify PASSED ===")