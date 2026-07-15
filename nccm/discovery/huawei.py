from __future__ import annotations

import re

from nccm.models import NetDriverProfile


def classify_huawei_display_version(text: str) -> NetDriverProfile:
    t = text or ""
    if re.search(r"USG|Secospace|Unified Security Gateway", t, re.I):
        ver = _first(r"Version\s+([\d.]+)", t) or "1.0"
        return NetDriverProfile("huawei", "usg6000", ver)
    if re.search(r"CE\d|CloudEngine|CE6800|sysname\s+huawei_ce", t, re.I):
        ver = _first(r"!Software Version\s+(\S+)", t) or _first(
            r"Version\s+[\d.]+\s+\(([^)]+)\)", t
        ) or _first(r"V(\d+R\d+C\d+)", t) or "8.0"
        return NetDriverProfile("huawei", "ce", ver)
    if re.search(r"AR\d|Versatile Routing", t, re.I):
        ver = _first(r"Version\s+([\d.]+)", t) or "1.0"
        return NetDriverProfile("huawei", "ce", ver)
    return NetDriverProfile("huawei", "ce", "8.0")


def _first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.I)
    return m.group(1) if m else None