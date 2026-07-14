#!/usr/bin/env python3
import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
p = ROOT / ".hermes/plans/2026-07-14_150000-secure-api-tokens.md"
t = p.read_text(encoding="utf-8")
for n in ("api_tokens", "X-API-Key", "Phase A", "inventory:read", "尚未實作"):
    assert n in t, n
print("secure-api-tokens plan doc: OK")
print("=== ad-hoc plan-doc verify PASSED ===")