"""Parse Cisco IOS / IOS-XE stack members from show version / show switch output."""
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


_ROLE_ORDER = {
    "active": 0,
    "master": 0,
    "primary": 0,
    "standby": 1,
    "secondary": 1,
    "slave": 1,
    "member": 2,
    "unknown": 3,
}


def _role_rank(role: str) -> int:
    return _ROLE_ORDER.get((role or "").strip().lower(), 3)


def _looks_like_sw_version(token: str) -> bool:
    t = (token or "").strip()
    if not t:
        return False
    # Classic IOS image: 15.2(7)E10, 12.2(55)SE12
    if re.match(r"^\d+\.\d+\([^)]+\)[A-Za-z0-9]*$", t):
        return True
    if re.match(r"^\d+\.\d+\([^)]+\)$", t):
        return True
    # IOS-XE / IOS: 16.12.05, 17.09.04a
    if re.match(r"^\d+(\.\d+)+[a-zA-Z0-9]*$", t):
        return True
    return False


def _looks_like_cisco_serial(token: str) -> bool:
    t = (token or "").strip()
    if not t or t.lower() in ("unknown", "ready", "v01", "v02", "v03"):
        return False
    if _looks_like_sw_version(t):
        return False
    if re.match(r"^0x[0-9a-f.]+$", t, re.I):
        return False
    if re.match(r"^[A-Z]{3}[A-Z0-9]{3,}$", t, re.I):
        return True
    if len(t) >= 7 and re.match(r"^[A-Z0-9]+$", t, re.I):
        return True
    return False


def _is_missing_serial(serial: str) -> bool:
    s = (serial or "").strip()
    return not s or s.lower() == "unknown" or not _looks_like_cisco_serial(s)


def _parse_member_serial_from_body(body: str) -> str:
    for pat in (
        r"System [Ss]erial [Nn]umber\s*:\s*(\S+)",
        r"Serial [Nn]umber\s*:\s*(\S+)",
        r"Processor [Bb]oard ID\s+(\S+)",
    ):
        m = re.search(pat, body, re.I)
        if m and _looks_like_cisco_serial(m.group(1)):
            return m.group(1)
    return ""


def _parse_show_switch_member_serials(text: str) -> dict[int, str]:
    """Serials from show switch / stack_info Switch NN sections."""
    out: dict[int, str] = {}
    block_pat = re.compile(
        r"Switch\s+(\d+)\s*\n[-=\s]*\n(.*?)(?=^Switch\s+\d+\s*$|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    for m in block_pat.finditer(text or ""):
        num = int(m.group(1))
        serial = _parse_member_serial_from_body(m.group(2))
        if serial:
            out[num] = serial
    return out


def _ordered_system_serials(text: str) -> list[str]:
    seen: list[str] = []
    for m in re.finditer(
        r"System [Ss]erial [Nn]umber\s*:\s*(\S+)",
        text or "",
        re.IGNORECASE,
    ):
        s = m.group(1).strip()
        if s and _looks_like_cisco_serial(s) and s not in seen:
            seen.append(s)
    return seen


def _backfill_stack_serials(
    units: dict[int, StackUnit], combined: str, roles: dict[int, str]
) -> dict[int, StackUnit]:
    if not units:
        return units
    by_switch = _parse_show_switch_member_serials(combined)
    ordered = _ordered_system_serials(combined)
    nums_sorted = sorted(units.keys())
    active_nums = {
        n
        for n, r in roles.items()
        if (r or "").strip().lower() in ("active", "master", "primary")
    }
    if not active_nums:
        for n, u in units.items():
            if (u.role or "").strip().lower() in ("active", "master", "primary"):
                active_nums.add(n)

    updated: dict[int, StackUnit] = dict(units)
    for num in nums_sorted:
        u = updated[num]
        if not _is_missing_serial(u.serial):
            continue
        serial = by_switch.get(num, "")
        if not serial and ordered:
            idx = nums_sorted.index(num)
            if idx < len(ordered):
                serial = ordered[idx]
            elif num in active_nums and ordered:
                serial = ordered[0]
        if not serial:
            continue
        updated[num] = StackUnit(
            u.switch_num,
            u.role,
            u.model,
            serial,
            u.sw_version,
            u.hostname,
        )
    return updated


def _assign_model_serial_sw(model: str, tokens: list[str]) -> tuple[str, str, str]:
    """IOS-XE stack row tokens after Ports: Model [SW Version] Serial [H/W ...]."""
    model = model or (tokens[0] if tokens else "")
    rest = tokens[1:] if tokens and tokens[0] == model else tokens
    if not rest:
        return model, "", ""

    if len(rest) >= 2 and _looks_like_sw_version(rest[0]) and _looks_like_cisco_serial(rest[1]):
        return model, rest[1], rest[0]
    if _looks_like_cisco_serial(rest[0]):
        return model, rest[0], ""
    if _looks_like_sw_version(rest[0]) and len(rest) >= 2:
        return model, rest[1] if _looks_like_cisco_serial(rest[1]) else "", rest[0]
    if _looks_like_sw_version(rest[0]):
        return model, "", rest[0]
    return model, rest[0], ""


def _prefer_serial(candidate: str, fallback: str) -> str:
    if _looks_like_cisco_serial(candidate):
        return candidate
    if _looks_like_cisco_serial(fallback):
        return fallback
    if candidate and not _looks_like_sw_version(candidate):
        return candidate
    return fallback or candidate or ""


def normalize_stack_display_role(role: str, *, vendor: str = "") -> str:
    """Align Cisco stack roles with FortiGate HA labels (Primary / Secondary / Member)."""
    r = (role or "").strip().lower()
    if r in ("active", "master", "primary"):
        return "Primary"
    if r in ("standby", "secondary", "slave"):
        return "Secondary"
    if r in ("member",):
        return "Member"
    return (role or "Member").strip() or "Member"


def member_display_hostname(
    cluster_hostname: str,
    unit: StackUnit,
    *,
    vendor: str,
) -> str:
    """Per-member hostname for inventory (Forti HA uses parsed hostname; Cisco stack uses SW# suffix)."""
    h = (unit.hostname or "").strip()
    if h:
        return h
    base = (cluster_hostname or "").strip() or "unknown"
    v = (vendor or "").strip().lower()
    if v == "fortinet":
        return base
    return f"{base} · SW{unit.switch_num}"


def parse_huawei_stack_units(
    manufacture_text: str,
    *,
    default_sw: str = "",
    default_model: str = "",
) -> list[StackUnit]:
    """iStack / multi-member from manufacture-info Slot rows (≥2 distinct serials)."""
    from nccm.parsers.version import parse_huawei_manufacture_rows

    rows = parse_huawei_manufacture_rows(manufacture_text)
    if len(rows) < 2:
        return []
    primary_slot = min(r.slot for r in rows)
    units: list[StackUnit] = []
    for i, r in enumerate(sorted(rows, key=lambda x: x.slot), start=1):
        role = "Primary" if r.slot == primary_slot else "Member"
        units.append(
            StackUnit(
                switch_num=i,
                role=role,
                model=(r.model or default_model or "Unknown").strip(),
                serial=r.serial,
                sw_version=default_sw or "",
                hostname="",
            )
        )
    return sorted(units, key=lambda u: u.switch_num)


def is_cisco_stack_version(text: str) -> bool:
    t = text or ""
    if re.search(r"Switch/Stack\s+Mac", t, re.I):
        return True
    if re.search(r"^\s*\*?\d+\s+(Active|Standby|Member|Master)\s", t, re.M | re.I):
        return True
    blocks = re.findall(r"^Switch\s+(\d+)\s*$", t, re.M | re.I)
    if len(blocks) >= 2:
        return True
    if len(re.findall(r"^\s*\*?\s*\d+\s+\d+\s+\S+\s+\S+", t, re.M)) >= 2:
        return True
    return False


def _parse_role_table(text: str) -> dict[int, str]:
    roles: dict[int, str] = {}
    for m in re.finditer(
        r"^\s*\*?(\d+)\s+(Active|Standby|Member|Master)\b",
        text,
        re.MULTILINE | re.IGNORECASE,
    ):
        roles[int(m.group(1))] = m.group(2).capitalize()
    return roles


def _parse_switch_blocks(text: str, roles: dict[int, str]) -> dict[int, StackUnit]:
    units: dict[int, StackUnit] = {}
    block_pat = re.compile(
        r"Switch\s+(\d+)\s*\n[-\s]*\n(.*?)(?=^Switch\s+\d+\s*$|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    for m in block_pat.finditer(text):
        num = int(m.group(1))
        body = m.group(2)
        serial = _parse_member_serial_from_body(body)
        model_m = re.search(r"Model [Nn]umber\s*:\s*(\S+)", body)
        sw_m = re.search(r"Image\s+software\s+version\s*:\s*(\S+)", body, re.I)
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
    return units


def _parse_iosxe_port_table(text: str) -> dict[int, StackUnit]:
    """IOS-XE stack summary table inside show version (Switch# Ports Model [SW Ver] Serial ...)."""
    units: dict[int, StackUnit] = {}
    active_nums: set[int] = set()
    for line in text.splitlines():
        m = re.match(
            r"^\s*(\*?)\s*(\d+)\s+(\d+)\s+(\S+)\s+(.+?)\s*$",
            line,
        )
        if not m:
            continue
        starred = bool(m.group(1))
        num = int(m.group(2))
        model = m.group(4)
        tail_tokens = m.group(5).split()
        model, serial, sw = _assign_model_serial_sw(model, tail_tokens)
        if not serial and not model:
            continue
        if starred:
            active_nums.add(num)
        role = "Active" if starred else "Member"
        units[num] = StackUnit(
            switch_num=num,
            role=role,
            model=model or "Unknown",
            serial=serial or "Unknown",
            sw_version=sw,
            hostname="",
        )
    if len(units) >= 2 and len(active_nums) == 1:
        for num, u in list(units.items()):
            if num not in active_nums:
                units[num] = StackUnit(
                    u.switch_num,
                    "Standby",
                    u.model,
                    u.serial,
                    u.sw_version,
                    u.hostname,
                )
    return units


def _merge_units(*maps: dict[int, StackUnit]) -> dict[int, StackUnit]:
    merged: dict[int, StackUnit] = {}
    for m in maps:
        for num, u in m.items():
            if num not in merged:
                merged[num] = u
                continue
            prev = merged[num]
            merged[num] = StackUnit(
                num,
                u.role if u.role != "Member" else prev.role,
                u.model if u.model not in ("", "Unknown") else prev.model,
                _prefer_serial(u.serial, prev.serial),
                u.sw_version or prev.sw_version,
                u.hostname or prev.hostname,
            )
    return merged


def parse_cisco_stack_units(text: str, extra: str = "") -> list[StackUnit]:
    """Return stack members; empty if not a stack or unparseable."""
    combined = f"{text or ''}\n{extra or ''}".strip()
    if not is_cisco_stack_version(combined):
        return []

    roles = _parse_role_table(combined)
    units = _merge_units(
        _parse_switch_blocks(combined, roles),
        _parse_iosxe_port_table(combined),
    )
    units = _backfill_stack_serials(units, combined, roles)

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

    units = _backfill_stack_serials(units, combined, roles)
    ordered = sorted(units.values(), key=lambda u: (_role_rank(u.role), u.switch_num))
    return ordered


def config_anchor_unit(units: list[StackUnit]) -> StackUnit | None:
    """Member whose inventory row anchors virtual-IP config (Active/Master)."""
    if not units:
        return None
    for u in units:
        if u.role.lower() in ("active", "master", "primary"):
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

        role_m = re.search(r"(?i)\b(Primary|Secondary|Master|Slave)\b", line)
        if not role_m:
            continue
        role_raw = role_m.group(1).lower()
        role = "Primary" if role_raw in ("primary", "master") else "Secondary"

        rest = re.sub(r"(?i)^.*?(Primary|Secondary|Master|Slave)\s*:?\s*", "", line)

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
            if (
                tok.upper().startswith("FGT")
                or (
                    len(tok) >= 10
                    and tok.replace("-", "").replace("_", "").isalnum()
                    and not any(c in tok for c in "_-")
                )
            ):
                if serial is None:
                    serial = tok
            elif ("_" in tok or "-" in tok) and not tok.upper().startswith("FGT"):
                if hname is None:
                    hname = tok

        if hname is None or serial is None:
            for tok in tokens:
                if "=" in tok or "HA operating" in tok or "index" in tok.lower():
                    continue
                if not (
                    tok.upper().startswith("FGT")
                    or (len(tok) >= 10 and not any(c in tok for c in "_-"))
                ):
                    if hname is None and len(tok) > 3:
                        hname = tok
            for tok in tokens:
                if tok.upper().startswith("FGT") or (
                    len(tok) >= 10 and tok.replace("-", "").isalnum()
                ):
                    if serial is None:
                        serial = tok

        if not hname or not serial:
            continue
        if serial in seen:
            continue

        if hname.upper().startswith("FGT") and len(hname) > 10:
            for tok in tokens:
                if "_" in tok or ("-" in tok and not tok.upper().startswith("FGT")):
                    hname = tok
                    break

        if serial in seen or hname.upper().startswith("FGT") and len(hname) > 12:
            continue

        seen.add(serial)
        if "_" in hname or "-" in hname:
            units.append(StackUnit(0, role, "", serial, "", hname))

    if len(units) < 2:
        return []

    ordered = sorted(units, key=lambda u: (0 if u.role == "Primary" else 1, u.hostname or u.serial))
    result = []
    for i, u in enumerate(ordered, 1):
        result.append(StackUnit(i, u.role, u.model, u.serial, u.sw_version, u.hostname))
    return result