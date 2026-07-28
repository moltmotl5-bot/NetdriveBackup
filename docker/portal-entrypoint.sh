#!/bin/sh
set -eu

# Bind-mounted ./store is often root-owned from pre-Phase-3 Portal containers.
# Ensure the runtime user can write portal_auth.db, audit.db, schedules, etc.
if [ -d /data/store ]; then
  chown -R nccm:nccm /data/store 2>/dev/null || true
fi
chown -R nccm:nccm /app/logs 2>/dev/null || true

if [ "$(id -u)" = "0" ]; then
  exec su nccm -s /bin/sh -c 'exec "$@"' sh "$@"
fi

exec "$@"
