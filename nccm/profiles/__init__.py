from __future__ import annotations

import re
from dataclasses import dataclass

from nccm.models import NetDriverProfile


@dataclass(frozen=True)
class CommandSpec:
    artifact: str
    command: str
    agent_mode: str
    timeout: int = 120


def normalize_vendor(raw: str) -> str:
    v = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {"fortigate": "fortinet", "forti": "fortinet"}
    return aliases.get(v, v)


def default_agent_mode(vendor: str) -> str:
    """NetDriver execution mode per vendor plugin (_SUPPORTED_MODES)."""
    v = normalize_vendor(vendor)
    if v == "cisco":
        return "login"
    if v in ("huawei", "fortinet"):
        return "enable"
    raise ValueError(f"unsupported vendor: {vendor}")


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
            return normalize_profile_for_agent(hint)
    if v == "cisco":
        return NetDriverProfile("cisco", "catalyst", "17.0")
    if v == "huawei":
        return normalize_profile_for_agent(NetDriverProfile("huawei", "ce", "8.0"))
    if v == "fortinet":
        return normalize_profile_for_agent(NetDriverProfile("fortinet", "fortigate", "7.2"))
    raise ValueError(f"unsupported vendor: {vendor}")


def normalize_profile_for_agent(profile: NetDriverProfile) -> NetDriverProfile:
    """Map NCCM/discovered model strings to NetDriver Agent CommonRequest.model patterns."""
    v = normalize_vendor(profile.vendor)
    ver = (str(profile.version).strip() if profile.version else "") or "1.0"
    raw = (str(profile.model).strip().lower() if profile.model else "") or ""

    if v == "huawei":
        # Agent allows huawei + ce.*|usg.* only (plugins: huawei.ce in agent.yml).
        if re.fullmatch(r"usg.*", raw):
            model = raw
        elif re.search(r"usg", raw):
            model = "usg6000"
        elif raw in ("", "ce", "ar") or re.fullmatch(r"ce.*", raw):
            # AR routers: no ar.* plugin — use ce profile for SSH/exec.
            model = "ce" if raw in ("", "ce", "ar") else raw
        elif re.search(r"ce\d|cloudengine|s\d{4}", raw, re.I):
            model = "ce6800"
        else:
            model = "ce"
        return NetDriverProfile("huawei", model, ver)

    if v == "fortinet":
        model = raw if re.fullmatch(r"fortigate.*", raw) else "fortigate"
        return NetDriverProfile("fortinet", model, ver or "7.2")

    return profile


def profile_from_csv(vendor: str, model: str | None, version: str | None) -> NetDriverProfile | None:
    if not model or not str(model).strip():
        return None
    v = normalize_vendor(vendor)
    m = str(model).strip().lower()
    ver = (str(version).strip() if version else "") or "1.0"
    return normalize_profile_for_agent(NetDriverProfile(v, m, ver))


def cisco_running_config_command(model: str | None) -> str:
    """NX-OS (nexus) uses plain show running-config; Cisco IOS uses view full."""
    m = (model or "").strip().lower()
    if m == "nexus":
        return "show running-config"
    return "show running-config view full"


def version_command(vendor: str) -> str:
    v = normalize_vendor(vendor)
    if v == "cisco":
        return "show version"
    if v == "huawei":
        return "display version"
    if v == "fortinet":
        return "get system status"
    raise ValueError(vendor)


def cisco_backup_commands(model: str | None) -> list[CommandSpec]:
    m = (model or "").strip().lower()
    mode = "login"
    cfg_cmd = cisco_running_config_command(m)
    if m == "nexus":
        return [
            CommandSpec("version_info", "show version", mode),
            CommandSpec("config", cfg_cmd, mode, timeout=300),
            CommandSpec("interfaces", "show interface status", mode),
            CommandSpec("cdp", "show cdp neighbors", mode),
            CommandSpec("lldp", "show lldp neighbors", mode),
        ]
    return [
        CommandSpec("version_info", "show version", mode),
        CommandSpec("stack_info", "show switch", mode),
        CommandSpec("config", cfg_cmd, mode, timeout=300),
        CommandSpec("interfaces", "show interface status", mode),
        CommandSpec("cdp", "show cdp neighbors", mode),
        CommandSpec("lldp", "show lldp neighbors", mode),
    ]


def huawei_backup_commands() -> list[CommandSpec]:
    mode = "enable"
    return [
        CommandSpec("version_info", "display version", mode),
        CommandSpec("config", "display current-configuration", mode, timeout=300),
        CommandSpec("interfaces", "display interface brief", mode),
        CommandSpec("lldp", "display lldp neighbor brief", mode),
    ]


def fortinet_backup_commands() -> list[CommandSpec]:
    mode = "enable"
    return [
        CommandSpec("version_info", "get system status", mode),
        CommandSpec("ha_status", "get system ha status", mode),
        CommandSpec("config", "show full-configuration", mode, timeout=600),
        CommandSpec("interfaces", "get system interface physical", mode),
    ]


def backup_commands(vendor: str, model: str | None = None) -> list[CommandSpec]:
    v = normalize_vendor(vendor)
    if v == "cisco":
        return cisco_backup_commands(model)
    if v == "huawei":
        return huawei_backup_commands()
    if v == "fortinet":
        return fortinet_backup_commands()
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
        for pat in [
            r'set hostname\s+"?([A-Za-z0-9_.-]+)"?',
            r"Hostname:\s*([A-Za-z0-9_.-]+)",
        ]:
            m = re.search(pat, text, re.I)
            if m:
                val = m.group(1)
                if not (val.upper().startswith("FGT") and len(val) > 8):
                    return val
        m = re.search(r'set alias "([^"]+)"', text, re.I)
        if m:
            val = m.group(1)
            if not (val.upper().startswith("FGT") and len(val) > 8):
                return val
    if v == "huawei":
        m = re.search(r"sysname\s+(\S+)", text, re.I)
        if m:
            return m.group(1)
        m = re.search(r"<(\S+)>", text)
        if m:
            return m.group(1)
    return "unknown"