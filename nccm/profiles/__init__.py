from __future__ import annotations

import re
from dataclasses import dataclass

from nccm.models import NetDriverProfile


@dataclass(frozen=True)
class CommandSpec:
    artifact: str
    command: str
    mode: str = "enable"
    timeout: int = 120


def normalize_vendor(raw: str) -> str:
    v = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {"fortigate": "fortinet", "forti": "fortinet"}
    return aliases.get(v, v)


def default_probe_profile(vendor: str, port: int | None = None) -> NetDriverProfile:
    v = normalize_vendor(vendor)
    if port is not None:
        lab_by_port: dict[int, NetDriverProfile] = {
            18020: NetDriverProfile("cisco", "nexus", "9.6.0"),
            18037: NetDriverProfile("fortinet", "fortigate", "7.2"),
            18038: NetDriverProfile("huawei", "ce", "8.18"),
        }
        hint = lab_by_port.get(int(port))
        if hint and hint.vendor == v:
            return hint
    if v == "cisco":
        return NetDriverProfile("cisco", "catalyst", "17.0")
    if v == "huawei":
        return NetDriverProfile("huawei", "ce", "8.0")
    if v == "fortinet":
        return NetDriverProfile("fortinet", "fortigate", "7.2")
    raise ValueError(f"unsupported vendor: {vendor}")


def profile_from_csv(vendor: str, model: str | None, version: str | None) -> NetDriverProfile | None:
    if not model or not str(model).strip():
        return None
    v = normalize_vendor(vendor)
    m = str(model).strip().lower()
    ver = (str(version).strip() if version else "") or "1.0"
    return NetDriverProfile(v, m, ver)


def version_command(vendor: str) -> str:
    v = normalize_vendor(vendor)
    if v == "cisco":
        return "show version"
    if v == "huawei":
        return "display version"
    if v == "fortinet":
        return "get system status"
    raise ValueError(vendor)


def backup_commands(vendor: str, model: str | None = None) -> list[CommandSpec]:
    v = normalize_vendor(vendor)
    m = (model or "").strip().lower()
    if v == "cisco":
        if m == "nexus":
            return [
                CommandSpec("version_info", "show version"),
                CommandSpec("config", "show running-config", timeout=300),
                CommandSpec("interfaces", "show interface status"),
                CommandSpec("cdp", "show cdp neighbors"),
                CommandSpec("lldp", "show lldp neighbors"),
            ]
        return [
            CommandSpec("version_info", "show version"),
            CommandSpec("config", "show running-config", timeout=300),
            CommandSpec("interfaces", "show interface status"),
            CommandSpec("cdp", "show cdp neighbors"),
            CommandSpec("lldp", "show lldp neighbors"),
        ]
    if v == "huawei":
        return [
            CommandSpec("version_info", "display version"),
            CommandSpec("config", "display current-configuration", timeout=300),
            CommandSpec("interfaces", "display interface brief"),
            CommandSpec("lldp", "display lldp neighbor brief"),
        ]
    if v == "fortinet":
        return [
            CommandSpec("version_info", "get system status"),
            CommandSpec("config", "show full-configuration", timeout=600),
            CommandSpec("interfaces", "get system interface physical"),
        ]
    raise ValueError(f"unsupported vendor: {vendor}")


def hostname_from_output(vendor: str, text: str) -> str:
    v = normalize_vendor(vendor)
    if v == "cisco":
        m = re.search(r"Device name:\s*(\S+)", text, re.I)
        if m:
            return m.group(1)
        m = re.search(r"hostname\s+(\S+)", text, re.I)
        if m:
            return m.group(1)
    if v == "fortinet":
        m = re.search(r"Hostname:\s*(\S+)", text, re.I)
        if m:
            return m.group(1)
        m = re.search(r'set alias "([^"]+)"', text, re.I)
        if m:
            return m.group(1)
    if v == "huawei":
        m = re.search(r"sysname\s+(\S+)", text, re.I)
        if m:
            return m.group(1)
        m = re.search(r"<(\S+)>", text)
        if m:
            return m.group(1)
    return "unknown"