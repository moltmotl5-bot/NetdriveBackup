from __future__ import annotations

import re

from nccm.models import NetDriverProfile


def classify_cisco_show_version(text: str) -> NetDriverProfile:
    t = text or ""
    if re.search(r"NX-OS|Cisco Nexus", t, re.I):
        ver = _first(r"NXOS:\s*version\s+(\S+)", t) or "9.0"
        return NetDriverProfile("cisco", "nexus", ver)
    if re.search(r"Adaptive Security Appliance|ASA", t, re.I):
        ver = _first(r"Version\s+(\d+\.\d+(?:\.\d+)?)", t) or "9.8"
        return NetDriverProfile("cisco", "asa", ver)
    if re.search(r"ISR|ASR|Cisco IOS XE Software", t, re.I):
        ver = _first(r"Version\s+([^,\s]+)", t) or "17.0"
        if re.search(r"ASR", t, re.I):
            return NetDriverProfile("cisco", "asr", ver)
        return NetDriverProfile("cisco", "isr", ver)
    if re.search(r"Catalyst|IOS-XE|Cisco IOS Software", t, re.I):
        ver = _first(r"Version\s+([^,\s]+)", t) or "17.0"
        return NetDriverProfile("cisco", "catalyst", ver)
    return NetDriverProfile("cisco", "catalyst", "17.0")


def _first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.I)
    return m.group(1) if m else None