"""Parse Cisco IOS / IOS-XE stack members from show version output."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class StackUnit:
    switch_num: int
    role: str
    model: str
    serial: str
    sw_version: str = ""
    hostname: str = ""


_ROLE_ORDER = {"active": 0, "master": 0, "standby": 1, "member": 2, "unknown": 3}


def _role_rank(role: str) -> int:
    return _ROLE_ORDER.get((role or "").strip().lower(), 3)


def is_cisco_stack_version(text: str) -> bool:
    t = text or ""
    if re.search(r"Switch/Stack\s+Mac", t, re.I):
        return True
    if re.search(r"^\s*\*?\d+\s+(Active|Standby|Member|Master)\s", t, re.M | re.I):
        return True
    blocks = re.findall(r"^Switch\s+(\d+)\s*$", t, re.M | re.I)
    return len(blocks) >= 2


def parse_cisco_stack_units(text: str) -> list[StackUnit]:
    """Return stack members; empty if not a stack or unparseable."""
    if not is_cisco_stack_version(text):
        return []

    roles: dict[int, str] = {}
    for m in re.finditer(
        r"^\s*\*?(\d+)\s+(Active|Standby|Member|Master)\b",
        text,
        re.MULTILINE | re.IGNORECASE,
    ):
        roles[int(m.group(1))] = m.group(2).capitalize()

    units: dict[int, StackUnit] = {}
    block_pat = re.compile(
        r"Switch\s+(\d+)\s*\n[-\s]*\n(.*?)(?=^Switch\s+\d+\s*$|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    for m in block_pat.finditer(text):
        num = int(m.group(1))
        body = m.group(2)
        serial_m = re.search(
            r"System [Ss]erial [Nn]umber\s*:\s*(\S+)",
            body,
        ) or re.search(r"Processor [Bb]oard ID\s+(\S+)", body)
        model_m = re.search(r"Model [Nn]umber\s*:\s*(\S+)", body)
        sw_m = re.search(r"Image\s+software\s+version\s*:\s*(\S+)", body, re.I)
        serial = serial_m.group(1) if serial_m else ""
        model = model_m.group(1) if model_m else ""
        sw = sw_m.group(1) if sw_m else ""
        role = roles.get(num, "Member")
        units[num] = StackUnit(
            switch_num=num,
            role=role,
            model=model or "Unknown",
            serial=serial or "Unknown",
            sw_version=sw,
            hostname="",
        )

    if len(units) < 2 and roles:
        for num, role in roles.items():
            if num not in units:
                units[num] = StackUnit(
                    switch_num=num,
                    role=role,
                    model="Unknown",
                    serial="Unknown",
                    hostname="",
                )

    if len(units) < 2:
        return []

    ordered = sorted(units.values(), key=lambda u: (_role_rank(u.role), u.switch_num))
    return ordered


def config_anchor_unit(units: list[StackUnit]) -> StackUnit | None:
    """Member whose inventory row anchors virtual-IP config (Active/Master)."""
    if not units:
        return None
    for u in units:
        if u.role.lower() in ("active", "master"):
            return u
    return units[0]

def parse_fortigate_ha_units(text: str) -> list[StackUnit]:
    """Parse FortiGate HA cluster members from get system ha status or version.
    Returns empty list if not a cluster (<2 members) or standalone.
    """
    if not text:
        return []
    t = text or ""
    if re.search(r"Current HA mode:\s*standalone|HA mode:\s*standalone", t, re.I):
        return []

    units: list[StackUnit] = []
    patterns = [
        r"(?im)(Primary|Secondary|Master|Slave|Active|Standby)[\s:,-]+([A-Z0-9]{6,})\s*,?\s*([A-Za-z0-9_.-]+)",
    ]
    seen = set()
    for pat in patterns:
        for m in re.finditer(pat, t):
            role_raw = m.group(1).lower()
            serial = m.group(2)
            hname = m.group(3)
            if serial in seen:
                continue
            seen.add(serial)
            role = "Primary" if role_raw in ("primary", "master", "active") else "Secondary"
            units.append(StackUnit(
                switch_num=0,  # will renumber
                role=role,
                model="",
                serial=serial,
                sw_version="",
                hostname=hname,
            ))
    if len(units) < 2:
        return []
    # Primary first
    ordered = sorted(units, key=lambda u: (0 if u.role == "Primary" else 1, u.hostname or u.serial))
    result = []
    for i, u in enumerate(ordered, 1):
        result.append(StackUnit(
            switch_num=i,
            role=u.role,
            model=u.model,
            serial=u.serial,
            sw_version=u.sw_version,
            hostname=u.hostname,
        ))
    return result
