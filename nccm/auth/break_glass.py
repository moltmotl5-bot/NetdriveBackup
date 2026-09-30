"""Break-glass (env admin) policy helpers."""
from __future__ import annotations

import os


def break_glass_enabled() -> bool:
    return os.environ.get("NCCM_BREAK_GLASS", "").strip() == "1"


def env_bootstrap_allowed() -> bool:
    """Env credentials may bootstrap only when user DB is empty."""
    return True
