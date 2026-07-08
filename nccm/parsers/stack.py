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
        )

    if len(units) < 2 and roles:
        for num, role in roles.items():
            if num not in units:
                units[num] = StackUnit(
                    switch_num=num,
                    role=role,
                    model="Unknown",
                    serial="Unknown",
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