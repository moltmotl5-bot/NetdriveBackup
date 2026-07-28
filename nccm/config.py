from __future__ import annotations

import os
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]


def app_root() -> Path:
    return Path(os.environ.get("NCCM_APP_ROOT", _APP_ROOT))


def store_dir() -> Path:
    p = app_root() / os.environ.get("NCCM_STORE_DIR", "store")
    p.mkdir(parents=True, exist_ok=True)
    return p


def auth_db_path() -> Path:
    override = os.environ.get("NCCM_AUTH_DB", "").strip()
    if override:
        return Path(override)
    return store_dir() / "portal_auth.db"


def netdriver_url() -> str:
    return (os.environ.get("NCCM_NETDRIVER_URL") or "http://127.0.0.1:8000").rstrip("/")


def agent_hmac_secret() -> str:
    return (os.environ.get("NCCM_AGENT_HMAC_SECRET") or "").strip()


_DEFAULT_SSH_PORTS = frozenset({22, 2222})


def allowed_ssh_ports() -> frozenset[int]:
    raw = (os.environ.get("NCCM_ALLOWED_SSH_PORTS") or "").strip()
    if not raw:
        return _DEFAULT_SSH_PORTS
    ports: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        port = int(part)
        if port < 1 or port > 65535:
            raise ValueError(f"invalid port in NCCM_ALLOWED_SSH_PORTS: {port}")
        ports.add(port)
    return frozenset(ports) if ports else _DEFAULT_SSH_PORTS


WLC_VENDOR_ALIASES = frozenset(
    {"cisco_wlc", "huawei_wlc", "wlc", "aireos", "cisco-wlc"}
)