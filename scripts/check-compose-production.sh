#!/usr/bin/env bash
# Fail if production docker-compose.yml publishes Agent to the host.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="${ROOT}/docker-compose.yml"

if grep -E '^[[:space:]]*-[[:space:]]*"?(\$\{NETDRIVER_AGENT_PORT[^}]*\}|8000):8000' "$COMPOSE"; then
  echo "ERROR: docker-compose.yml must not publish Agent port 8000 to the host." >&2
  echo "Use docker-compose.dev.yml for localhost debugging." >&2
  exit 1
fi

if ! grep -q '^[[:space:]]*expose:' "$COMPOSE"; then
  echo "ERROR: docker-compose.yml must expose Agent port internally." >&2
  exit 1
fi

echo "OK: production compose does not publish Agent host port."
