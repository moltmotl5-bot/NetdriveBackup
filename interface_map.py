"""Interface Map: interface stanzas from config.txt + Status from interfaces.txt only."""
from __future__ import annotations

import os
import re

import pandas as pd

INTERFACE_COLUMNS = [
    "Port",
    "Description",
    "Status",
    "Vlan",
    "Speed",
    "Type",
]

_CISCO_STATUS = re.compile(
    r"^(connected|notconnect|notconnected|disabled|err-disabled|suspended|"
    r"inactive|xcvrabsen|monitoring|unassigned|sfpabsent)$",
    re.I,
)


def strip_nccm_header(text: str) -> str:
    if (text or "").lstrip().startswith("# NCCM command:"):
        return re.sub(
            r"^# NCCM command:.*?\n\n",
            "",
            text,
            count=1,
            flags=re.DOTALL,
        )
    return text or ""


def latest_snapshot_dir(device_path: str) -> tuple[str | None, str | None]:
    if not device_path or not os.path.isdir(device_path):
        return None, None
    dates = sorted(
        [
            d
            for d in os.listdir(device_path)
            if os.path.isdir(os.path.join(device_path, d))
        ],
        reverse=True,
    )
    if not dates:
        return None, None
    return dates[0], os.path.join(device_path, dates[0])


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=INTERFACE_COLUMNS)


def _row(
    port: str,
    description: str = "",
    status: str = "",
    vlan: str = "",
    speed: str = "",
    typ: str = "",
) -> dict[str, str]:
    return {
        "Port": port.strip(),
        "Description": description.strip(),
        "Status": status.strip(),
        "Vlan": vlan.strip(),
        "Speed": speed.strip(),
        "Type": typ.strip(),
    }


def iface_name_keys(name: str) -> set[str]:
    """Aliases for matching config names to ``show interface status`` short names."""
    n = (name or "").strip()
    if not n:
        return set()
    keys = {n, n.lower()}
    pairs = [
        ("GigabitEthernet", "Gi"),
        ("TenGigabitEthernet", "Te"),
        ("FastEthernet", "Fa"),
        ("FortyGigabitEthernet", "Fo"),
        ("HundredGigE", "Hu"),
        ("Ethernet", "Eth"),
        ("Port-channel", "Po"),
    ]
    for long_p, short_p in pairs:
        if re.match(rf"^{re.escape(long_p)}", n, re.I):
            rest = re.sub(rf"^{re.escape(long_p)}", "", n, count=1, flags=re.I)
            keys.add(short_p + rest)
            keys.add((short_p + rest).lower())
        if re.match(rf"^{re.escape(short_p)}", n, re.I):
            rest = re.sub(rf"^{re.escape(short_p)}", "", n, count=1, flags=re.I)
            keys.add(long_p + rest)
            keys.add((long_p + rest).lower())
    return keys


def _looks_like_port(token: str) -> bool:
    if not token or token.lower() in ("port", "interface", "vlan"):
        return False
    return bool(re.search(r"\d", token)) or token.lower().startswith(
        ("gi", "te", "fa", "eth", "po", "vlan", "mgmt", "ge", "xe", "hu", "fo", "ap")
    )


def iter_ios_interface_blocks(text: str) -> list[tuple[str, list[str]]]:
    """Cisco/Huawei-style ``interface …`` stanzas until ``!`` or next interface."""
    text = strip_nccm_header(text)
    blocks: list[tuple[str, list[str]]] = []
    current: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal current, buf
        if current:
            blocks.append((current, buf))
        current = None
        buf = []

    for line in text.splitlines():
        m = re.match(r"^interface\s+(\S+)", line, re.I)
        if m:
            flush()
            current = m.group(1)
            continue
        if current is None:
            continue
        if line.strip() == "!":
            flush()
            continue
        if re.match(r"^interface\s+", line, re.I):
            flush()
            current = re.match(r"^interface\s+(\S+)", line, re.I).group(1)  # type: ignore[union-attr]
            continue
        buf.append(line)
    flush()
    return blocks


def _fields_from_cisco_block(lines: list[str]) -> dict[str, str]:
    desc = vlan = speed = typ = ""
    mode_trunk = False
    for line in lines:
        s = line.strip()
        dm = re.match(r"^description\s+(.+)", s, re.I)
        if dm:
            desc = dm.group(1).strip()
            continue
        if re.match(r"^switchport mode trunk", s, re.I):
            mode_trunk = True
            vlan = "trunk"
            continue
        m = re.match(r"^switchport access vlan\s+(\S+)", s, re.I)
        if m:
            vlan = m.group(1)
            continue
        m = re.match(r"^switchport trunk native vlan\s+(\S+)", s, re.I)
        if m and not vlan:
            vlan = f"native {m.group(1)}"
            continue
        m = re.match(r"^speed\s+(\S+)", s, re.I)
        if m:
            speed = m.group(1)
            continue
        if re.match(r"^channel-group", s, re.I):
            typ = "port-channel member"
        elif re.match(r"^switchport", s, re.I) and not typ:
            typ = "L2 switchport"
    if mode_trunk and vlan != "trunk":
        vlan = "trunk"
    return {"description": desc, "vlan": vlan, "speed": speed, "type": typ or "interface"}


def _fields_from_huawei_block(lines: list[str]) -> dict[str, str]:
    desc = vlan = speed = typ = ""
    for line in lines:
        s = line.strip()
        dm = re.match(r"^description\s+(.+)", s, re.I)
        if dm:
            desc = dm.group(1).strip()
        if re.match(r"^port link-type trunk", s, re.I):
            vlan = "trunk"
        m = re.match(r"^port default vlan\s+(\S+)", s, re.I)
        if m:
            vlan = m.group(1)
        if re.match(r"^eth-trunk", s, re.I):
            typ = "eth-trunk"
    return {"description": desc, "vlan": vlan, "speed": speed, "type": typ or "interface"}


def extract_interfaces_from_config(config_text: str | None, vendor: str) -> list[dict[str, str]]:
    if not config_text or not config_text.strip():
        return []
    v = (vendor or "").lower()
    blocks = iter_ios_interface_blocks(config_text)
    rows: list[dict[str, str]] = []
    for ifname, lines in blocks:
        if v == "huawei":
            fields = _fields_from_huawei_block(lines)
        else:
            fields = _fields_from_cisco_block(lines)
        rows.append(
            _row(
                ifname,
                fields["description"],
                "",
                fields["vlan"],
                fields["speed"],
                fields["type"],
            )
        )
    return rows


def parse_cisco_interface_status_map(text: str) -> dict[str, str]:
    """Port -> Status only from ``show interface status``."""
    text = strip_nccm_header(text)
    status_by_key: dict[str, str] = {}
    started = False
    for line in text.splitlines():
        raw = line.rstrip()
        if not raw.strip():
            continue
        if re.search(r"Port\s+Name\s+Status", raw, re.I):
            started = True
            continue
        if not started and re.search(r"Port.*Status.*Vlan", raw, re.I):
            started = True
            continue
        if not started or re.match(r"^[-=]{3,}", raw):
            continue
        parts = raw.split()
        if len(parts) < 3 or not _looks_like_port(parts[0]):
            continue
        port = parts[0]
        status_idx = None
        for i in range(1, len(parts)):
            if _CISCO_STATUS.match(parts[i]):
                status_idx = i
                break
        if status_idx is None:
            continue
        status = parts[status_idx]
        for k in iface_name_keys(port):
            status_by_key[k] = status
    return status_by_key


def parse_cisco_ip_brief_status_map(text: str) -> dict[str, str]:
    text = strip_nccm_header(text)
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(
            r"^(\S+)\s+\S+\s+\S+\s+\S+\s+(up|down|administratively down)\s+"
            r"(up|down|administratively down)\s*$",
            line.strip(),
            re.I,
        )
        if not m:
            continue
        st = f"{m.group(2)}/{m.group(3)}"
        for k in iface_name_keys(m.group(1)):
            out[k] = st
    return out


def parse_huawei_brief_status_map(text: str) -> dict[str, str]:
    text = strip_nccm_header(text)
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(
            r"^(\S+)\s+(up|down|\*down)\s+(up|down|\*down)\s+",
            line.strip(),
            re.I,
        )
        if not m:
            continue
        st = f"PHY:{m.group(2)} / Prot:{m.group(3)}"
        for k in iface_name_keys(m.group(1)):
            out[k] = st
    return out


def parse_fortinet_physical_status_map(text: str) -> dict[str, str]:
    text = strip_nccm_header(text)
    out: dict[str, str] = {}
    blocks = re.split(r"==\s*\[\s*([^\]]+)\s*\]", text)
    i = 1
    while i + 1 < len(blocks):
        port = blocks[i].strip()
        body = blocks[i + 1]
        i += 2
        if not port or port.lower() in ("onboard", "slot"):
            continue
        fields = dict(
            re.findall(r"^\s*([a-zA-Z0-9_]+)\s*:\s*(.+)$", body, re.MULTILINE)
        )
        st = fields.get("status", fields.get("link", ""))
        if st:
            for k in iface_name_keys(port):
                out[k] = st.strip()
    return out


def parse_status_map(interfaces_text: str | None, vendor: str) -> tuple[dict[str, str], str]:
    if not interfaces_text or not interfaces_text.strip():
        return {}, "no_interfaces_txt"
    body = strip_nccm_header(interfaces_text)
    v = (vendor or "").lower()
    candidates: list[tuple[str, dict[str, str]]] = []

    m = parse_cisco_interface_status_map(body)
    if m:
        candidates.append(("cisco_interface_status", m))
    m = parse_cisco_ip_brief_status_map(body)
    if m:
        candidates.append(("cisco_ip_interface_brief", m))
    if v == "huawei":
        m = parse_huawei_brief_status_map(body)
        if m:
            candidates.append(("huawei_interface_brief", m))
    m = parse_huawei_brief_status_map(body)
    if m:
        candidates.append(("huawei_interface_brief", m))
    if v in ("fortinet",):
        m = parse_fortinet_physical_status_map(body)
        if m:
            candidates.append(("fortinet_physical", m))
    m = parse_fortinet_physical_status_map(body)
    if m:
        candidates.append(("fortinet_physical", m))

    if not candidates:
        return {}, "unparsed_status"
    best_id, best_map = max(candidates, key=lambda x: len(x[1]))
    return best_map, best_id


def lookup_status(port: str, status_map: dict[str, str]) -> str:
    lower_map = {k.lower(): v for k, v in status_map.items()}
    for k in iface_name_keys(port):
        if k in status_map:
            return status_map[k]
        if k.lower() in lower_map:
            return lower_map[k.lower()]
    return ""


def merge_config_and_status(
    config_rows: list[dict[str, str]],
    status_map: dict[str, str],
) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    seen_ports: set[str] = set()
    for r in config_rows:
        port = r["Port"]
        seen_ports.add(port)
        rows.append(
            _row(
                port,
                r.get("Description", ""),
                lookup_status(port, status_map),
                r.get("Vlan", ""),
                r.get("Speed", ""),
                r.get("Type", ""),
            )
        )
    for port_key, status in status_map.items():
        if any(port_key in iface_name_keys(p) for p in seen_ports):
            continue
        if not _looks_like_port(port_key):
            continue
        rows.append(_row(port_key, "", status, "", "", "status-only"))
    if not rows:
        return _empty_frame()
    df = pd.DataFrame(rows, columns=INTERFACE_COLUMNS)
    return df.drop_duplicates(subset=["Port"], keep="first").reset_index(drop=True)


def build_interface_map_table(
    config_text: str | None,
    interfaces_text: str | None,
    vendor: str,
) -> tuple[pd.DataFrame, str, str]:
    config_rows = extract_interfaces_from_config(config_text, vendor)
    status_map, status_parser = parse_status_map(interfaces_text, vendor)
    df = merge_config_and_status(config_rows, status_map)
    if config_rows and status_map:
        note = "config.txt（介面設定）+ interfaces.txt（Status）"
    elif config_rows:
        note = "config.txt（介面設定）；interfaces.txt 無可用 Status"
    elif status_map:
        note = "僅 interfaces.txt（Status）；config 無 interface 區段"
    else:
        note = "無法從 config / interfaces 建立表格"
    return df, note, status_parser


def format_config_interface_snippets(config_text: str | None, limit: int = 120) -> str:
    if not config_text:
        return ""
    blocks = iter_ios_interface_blocks(config_text)
    parts = []
    for name, lines in blocks[:limit]:
        body = "\n".join(lines).strip()
        parts.append(f"interface {name}\n{body}")
    text = "\n!\n".join(parts)
    if len(blocks) > limit:
        text += f"\n…（其餘 {len(blocks) - limit} 個介面已省略）"
    return text


def load_device_interface_table(
    device_path: str,
    vendor: str,
    snapshot: str | None = None,
) -> tuple[str | None, pd.DataFrame, str, str, str | None, str | None]:
    """Return ts, df, source_note, status_parser, raw_interfaces, config_snippets."""
    ts, snap_dir = latest_snapshot_dir(device_path)
    if snapshot:
        cand = os.path.join(device_path, snapshot)
        if os.path.isdir(cand):
            ts, snap_dir = snapshot, cand
    if not snap_dir:
        return None, _empty_frame(), "no backup", "none", None, None

    iface_path = os.path.join(snap_dir, "interfaces.txt")
    config_path = os.path.join(snap_dir, "config.txt")
    iface_text: str | None = None
    config_text: str | None = None
    if os.path.isfile(iface_path):
        with open(iface_path, encoding="utf-8", errors="replace") as f:
            iface_text = f.read()
    if os.path.isfile(config_path):
        with open(config_path, encoding="utf-8", errors="replace") as f:
            config_text = f.read()

    df, note, status_parser = build_interface_map_table(
        config_text, iface_text, vendor
    )
    snippets = format_config_interface_snippets(config_text)
    return ts, df, note, status_parser, iface_text, snippets or None