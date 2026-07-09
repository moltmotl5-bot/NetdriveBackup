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
    """Parse FortiGate HA from ha_status.txt.
    Goal: exactly 2 rows with real hostname + correct serial.
    Format supported (flexible):
      Primary: H3_Internal_401F_Pri, FG4H1FT925902510, 0
      Secondary: H3_Internal_401F_Sec, FG4H1FT925902507, 1
    """
    if not text:
        return []
    t = text or ""
    if re.search(r"standalone", t, re.I):
        return []

    units = []
    seen = set()

    for line in t.splitlines():
        line = line.strip()
        if not line:
            continue

        # Find role
        role_m = re.search(r"(?i)\b(Primary|Secondary|Master|Slave)\b", line)
        if not role_m:
            continue
        role_raw = role_m.group(1).lower()
        role = "Primary" if role_raw in ("primary", "master") else "Secondary"

        # Remove the role part and common noise
        rest = re.sub(r"(?i)^.*?(Primary|Secondary|Master|Slave)\s*:?\s*", "", line)

        # Split by comma or whitespace
        raw_tokens = re.split(r"[,\s]+", rest)
        tokens = [t.strip() for t in raw_tokens if t.strip()]

        hname = None
        serial = None

        for tok in tokens:
            tok = tok.strip()
            if not tok or len(tok) < 3:
                continue
            if "=" in tok or "HA operating" in tok or "index" in tok.lower():
                continue
            # Serial: starts with FGT or long pure alphanum without _ -
            if (tok.upper().startswith("FGT") or (len(tok) >= 10 and tok.replace("-", "").replace("_", "").isalnum() and not any(c in tok for c in "_-"))):
                if serial is None:
                    serial = tok
            # Hostname: has _ or - , or looks like a named device, not serial
            elif ("_" in tok or "-" in tok) and not tok.upper().startswith("FGT"):
                if hname is None:
                    hname = tok

        # Fallback if still missing
        if hname is None or serial is None:
            # Try to pick the non-serial looking token as hostname
            for tok in tokens:
                if "=" in tok or "HA operating" in tok or "index" in tok.lower():
                    continue
                if not (tok.upper().startswith("FGT") or (len(tok) >= 10 and not any(c in tok for c in "_-"))):
                    if hname is None and len(tok) > 3:
                        hname = tok
            for tok in tokens:
                if tok.upper().startswith("FGT") or (len(tok) >= 10 and tok.replace("-", "").isalnum()):
                    if serial is None:
                        serial = tok

        if not hname or not serial:
            continue
        if serial in seen:
            continue

        # Extra safety: hostname should not look like serial
        if hname.upper().startswith("FGT") and len(hname) > 10:
            # swap if we have another candidate
            for tok in tokens:
                if "_" in tok or ("-" in tok and not tok.upper().startswith("FGT")):
                    hname = tok
                    break

        if serial in seen or hname.upper().startswith("FGT") and len(hname) > 12:
            continue

        seen.add(serial)
        # Only accept if hostname looks like a real named device (has _ or - )
        if "_" in hname or "-" in hname:
            units.append(StackUnit(0, role, "", serial, "", hname))

    if len(units) < 2:
        return []

    ordered = sorted(units, key=lambda u: (0 if u.role == "Primary" else 1, u.hostname or u.serial))
    result = []
    for i, u in enumerate(ordered, 1):
        result.append(StackUnit(i, u.role, u.model, u.serial, u.sw_version, u.hostname))
    return result


