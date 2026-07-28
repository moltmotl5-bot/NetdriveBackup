"""CSV field validation for device import (Site, IP, Port, hostname hint)."""
from __future__ import annotations

import ipaddress
import re
from typing import Iterable

from nccm.config import allowed_ssh_ports

_SITE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HOSTNAME_HINT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_site(raw: str, *, row_hint: str = "") -> str:
    site = (raw or "").strip()
    if not site:
        raise ValueError(f"Site is required{row_hint}")
    if ".." in site or "/" in site or "\\" in site:
        raise ValueError(f"invalid Site{row_hint}: {site!r}")
    if not _SITE_RE.fullmatch(site):
        raise ValueError(f"invalid Site{row_hint}: {site!r}")
    return site


def validate_ip(raw: str, *, row_hint: str = "") -> str:
    text = (raw or "").strip()
    if not text:
        raise ValueError(f"IP is required{row_hint}")
    try:
        addr = ipaddress.ip_address(text)
    except ValueError as exc:
        raise ValueError(f"invalid IP{row_hint}: {text!r}") from exc
    return str(addr)


def validate_port(raw: str | int | None, *, row_hint: str = "", allowlist: Iterable[int] | None = None) -> int:
    if raw is None or str(raw).strip() == "":
        port = 22
    else:
        try:
            port = int(str(raw).strip())
        except ValueError as exc:
            raise ValueError(f"invalid Port{row_hint}: {raw!r}") from exc
    if port < 1 or port > 65535:
        raise ValueError(f"Port out of range{row_hint}: {port}")
    allowed = set(allowlist or allowed_ssh_ports())
    if port not in allowed:
        raise ValueError(f"Port not allowed{row_hint}: {port} (allowed: {sorted(allowed)})")
    return port


def validate_hostname_hint(raw: str | None, *, row_hint: str = "") -> str | None:
    hint = (raw or "").strip()
    if not hint:
        return None
    if len(hint) > 128:
        raise ValueError(f"hostname hint too long{row_hint}")
    if not _HOSTNAME_HINT_RE.fullmatch(hint):
        raise ValueError(f"invalid hostname hint{row_hint}: {hint!r}")
    return hint
