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


WLC_VENDOR_ALIASES = frozenset(
    {"cisco_wlc", "huawei_wlc", "wlc", "aireos", "cisco-wlc"}
)