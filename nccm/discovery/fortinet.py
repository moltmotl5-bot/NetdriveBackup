from __future__ import annotations

import re

from nccm.models import NetDriverProfile


def classify_fortinet_status(text: str) -> NetDriverProfile:
    t = text or ""
    ver = _first(r"#config-version=FGVMK6-([\d.]+)", t) or _first(
        r"Version:\s*FortiGate[^\s]*\s+v([\d.]+)", t
    ) or _first(r"v([\d.]+),build", t) or "7.2"
    return NetDriverProfile("fortinet", "fortigate", ver)


def _first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.I)
    return m.group(1) if m else None