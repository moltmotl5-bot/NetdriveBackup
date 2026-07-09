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
    """Parse FortiGate HA members from ha_status.txt.
    Supports the recommended format:
      Primary: hostname, serial, HAindex
      Secondary: hostname, serial, HAindex
    Falls back to more general parsing if needed.
    """
    if not text:
        return []
    t = text or ""
    if re.search(r"standalone", t, re.I):
        return []

    units = []
    seen = set()

    # Priority: specific "Primary:/Secondary:" comma format as recommended
    for line in t.splitlines():
        line = line.strip()
        if not line:
            continue

        m = re.match(r"(?i)^(Primary|Secondary|Master|Slave)\s*:\s*(.+)", line)
        if m:
            role_raw = m.group(1)
            rest = m.group(2).strip()
            parts = [p.strip() for p in rest.split(",") if p.strip()]

            # User recommended: hostname, serial, HAindex
            if len(parts) >= 2:
                hname = parts[0]
                serial = parts[1]
                ha_index_str = parts[2] if len(parts) > 2 else ""

                # Skip if this looks like the old serial-first format or garbage
                if not hname or not serial:
                    continue

                role = "Primary" if role_raw.lower() in ("primary", "master") else "Secondary"

                if serial in seen:
                    continue
                seen.add(serial)

                # Use HAindex for switch_num if valid, else sequential
                try:
                    switch_num = int(ha_index_str) + 1 if ha_index_str.isdigit() else len(units) + 1
                except:
                    switch_num = len(units) + 1

                units.append(StackUnit(switch_num, role, "", serial, "", hname))

    if len(units) >= 2:
        ordered = sorted(units, key=lambda u: (0 if u.role == "Primary" else 1, u.hostname or u.serial))
        result = []
        for i, u in enumerate(ordered, 1):
            result.append(StackUnit(i, u.role, u.model, u.serial, u.sw_version, u.hostname))
        return result

    # Fallback to previous robust heuristic parser (for other formats)
    units = []
    seen = set()
    for line in t.splitlines():
        line = line.strip()
        if not line:
            continue
        role_m = re.search(r"(?i)\b(Primary|Secondary|Master|Slave|Active|Standby)\b", line)
        if not role_m:
            continue
        role_raw = role_m.group(1).lower()
        role = "Primary" if role_raw in ("primary", "master", "active") else "Secondary"

        serials = re.findall(r"\b([A-Za-z0-9]{6,})\b", line)
        serial = None
        for s in serials:
            if s.startswith("FGT") or len(s) > 10:
                serial = s
                break
        if not serial and serials:
            serial = serials[0]
        if not serial or serial in seen:
            continue

        hname = ""
        candidates = re.findall(r"\b([A-Za-z][A-Za-z0-9_.-]{2,})\b", line)
        for c in candidates:
            if c.lower() in ("primary", "secondary", "master", "slave", "unit", "group"):
                continue
            if c == serial:
                continue
            if "-" in c or (not c.upper().startswith("FGT") and not re.match(r"^[A-Za-z0-9]{6,}$", c)):
                hname = c
                break
        if not hname:
            for c in candidates:
                if c != serial and c.lower() not in ("primary", "secondary", "master", "slave"):
                    hname = c
                    break
        if not hname:
            hname = serial

        seen.add(serial)
        units.append(StackUnit(0, role, "", serial, "", hname))

    if len(units) < 2:
        return []

    ordered = sorted(units, key=lambda u: (0 if u.role == "Primary" else 1, u.hostname or u.serial))
    result = [StackUnit(i+1, u.role, u.model, u.serial, u.sw_version, u.hostname) for i, u in enumerate(ordered)]
    return result


