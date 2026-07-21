#!/usr/bin/env bash
# Lightweight Compose smoke — not a full UAT suite.
# Usage: docker compose up -d --build && ./scripts/smoke-compose.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORTAL_URL="${NCCM_SMOKE_PORTAL_URL:-http://127.0.0.1:8080}"
AGENT_URL="${NCCM_SMOKE_AGENT_URL:-http://127.0.0.1:8000}"

echo "== smoke: agent health =="
curl -sf "${AGENT_URL}/health" | head -c 200
echo

echo "== smoke: portal root =="
code=$(curl -s -o /dev/null -w "%{http_code}" "${PORTAL_URL}/" || true)
# login redirect or 200 both OK
if [[ "$code" != "200" && "$code" != "303" && "$code" != "302" && "$code" != "307" ]]; then
  echo "portal HTTP $code (expected 200/3xx)" >&2
  exit 1
fi
echo "portal HTTP $code OK"

echo "== smoke: api health (no key) =="
curl -sf "${PORTAL_URL}/api/v1/health" | grep -q ok

echo "=== ad-hoc smoke-compose PASSED ==="
