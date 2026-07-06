"""Parse interfaces.txt (and config fallback) from NCCM backups into a uniform table."""
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

_CISCO_IFACE = re.compile(
    r"^(?:Gi|GigabitEthernet|Te|TenGigabitEthernet|Fa|FastEthernet|Eth|Ethernet|"
    r"Po|Port-channel|Vlan|mgmt|Hu|Fo|Lo|Ap|GE|XE|BE|Bundle-Ether|"
    r"FortyGigabitEthernet|HundredGigE)\S*$",
    re.I,
)

_CISCO_STATUS = re.compile(
    r"^(connected|notconnect|notconnected|disabled|err-disabled|suspended|"
    r"inactive|xcvrabsen|monitoring|unassigned|sfpabsent|sfpAbsent)$",
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


def _looks_like_port(token: str) -> bool:
    if not token or token.lower() in ("port", "interface", "vlan"):
        return False
    if _CISCO_IFACE.match(token):
        return True
    if re.match(r"^[A-Za-z][\w./:-]+$", token) and re.search(r"\d", token):
        return True
    return False


def parse_cisco_interface_status_tokenized(text: str) -> pd.DataFrame:
    """Cisco/Nexus ``show interface status`` — token-based (handles spaces in Name)."""
    text = strip_nccm_header(text)
    rows: list[dict[str, str]] = []
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
        if not started:
            continue
        if re.match(r"^[-=]{3,}", raw):
            continue

        parts = raw.split()
        if len(parts) < 4 or not _looks_like_port(parts[0]):
            continue

        port = parts[0]
        status_idx = None
        for i in range(1, len(parts)):
            if _CISCO_STATUS.match(parts[i]):
                status_idx = i
                break
        if status_idx is None or status_idx < 2:
            cols = re.split(r"\s{2,}", raw.strip())
            if len(cols) >= 4 and _looks_like_port(cols[0]):
                if len(cols) >= 7:
                    rows.append(
                        _row(
                            cols[0],
                            cols[1],
                            cols[2],
                            cols[3],
                            cols[5],
                            cols[6],
                        )
                    )
                elif len(cols) >= 5:
                    rows.append(_row(cols[0], cols[1], cols[2], cols[3], cols[4], ""))
            continue

        name = " ".join(parts[1:status_idx])
        status = parts[status_idx]
        rest = parts[status_idx + 1 :]
        vlan = rest[0] if len(rest) >= 1 else ""
        speed = rest[2] if len(rest) >= 3 else (rest[1] if len(rest) == 2 else "")
        typ = " ".join(rest[3:]) if len(rest) >= 4 else ""
        rows.append(_row(port, name, status, vlan, speed, typ))

    return pd.DataFrame(rows, columns=INTERFACE_COLUMNS) if rows else _empty_frame()


def parse_cisco_ip_interface_brief(text: str) -> pd.DataFrame:
    text = strip_nccm_header(text)
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "Interface" in line and "IP-Address" in line:
            continue
        m = re.match(
            r"^(\S+)\s+\S+\s+\S+\s+\S+\s+"
            r"(up|down|administratively down)\s+"
            r"(up|down|administratively down)\s*$",
            line,
            re.I,
        )
        if m:
            iface, link, proto = m.group(1), m.group(2), m.group(3)
            rows.append(
                _row(
                    iface,
                    "",
                    f"Line:{link} / Protocol:{proto}",
                    "",
                    "",
                    "",
                )
            )
    return pd.DataFrame(rows, columns=INTERFACE_COLUMNS) if rows else _empty_frame()


def parse_cisco_interface_summary(text: str) -> pd.DataFrame:
    """AireOS / legacy ``show interface summary`` style blocks."""
    text = strip_nccm_header(text)
    rows: list[dict[str, str]] = []
    current_port = ""
    for line in text.splitlines():
        m = re.match(r"^\s*Interface\s+(\S+)\s+", line, re.I)
        if m:
            current_port = m.group(1)
            continue
        if current_port and re.search(r"Status|State", line, re.I):
            st_m = re.search(r"(up|down|disabled)", line, re.I)
            rows.append(
                _row(
                    current_port,
                    "",
                    st_m.group(1) if st_m else line.strip(),
                    "",
                    "",
                    "summary",
                )
            )
            current_port = ""
    return pd.DataFrame(rows, columns=INTERFACE_COLUMNS) if rows else _empty_frame()


def parse_huawei_interface_brief(text: str) -> pd.DataFrame:
    text = strip_nccm_header(text)
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        m = re.match(
            r"^(\S+)\s+(up|down|\*down)\s+(up|down|\*down)\s+",
            line.strip(),
            re.I,
        )
        if not m:
            continue
        iface, phy, proto = m.group(1), m.group(2), m.group(3)
        status = f"PHY:{phy} / Protocol:{proto}"
        rows.append(_row(iface, "", status, "", "", "Ethernet"))
    return pd.DataFrame(rows, columns=INTERFACE_COLUMNS) if rows else _empty_frame()


def parse_fortinet_interface_physical(text: str) -> pd.DataFrame:
    text = strip_nccm_header(text)
    rows: list[dict[str, str]] = []
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
        status = fields.get("status", fields.get("link", ""))
        speed = fields.get("speed", fields.get("speed-duplex", ""))
        vlan = fields.get("vlan_id", fields.get("vlanid", ""))
        desc = fields.get("alias", fields.get("description", ""))
        typ = fields.get("type", "physical")
        rows.append(_row(port, desc, status, str(vlan), speed, typ))
    return pd.DataFrame(rows, columns=INTERFACE_COLUMNS) if rows else _empty_frame()


def parse_interfaces_from_config(text: str) -> pd.DataFrame:
    text = strip_nccm_header(text)
    rows: list[dict[str, str]] = []
    current_if: str | None = None
    desc = ""
    for line in text.splitlines():
        m = re.match(r"^\s*interface\s+(\S+)", line, re.I)
        if m:
            if current_if:
                rows.append(_row(current_if, desc, "", "", "", "config"))
            current_if = m.group(1)
            desc = ""
            continue
        if current_if:
            dm = re.match(r"^\s*description\s+(.+)", line, re.I)
            if dm:
                desc = dm.group(1).strip()
    if current_if:
        rows.append(_row(current_if, desc, "", "", "", "config"))
    return pd.DataFrame(rows, columns=INTERFACE_COLUMNS) if rows else _empty_frame()


def _score_frame(df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    score = len(df)
    for _, r in df.iterrows():
        if _looks_like_port(str(r.get("Port", ""))):
            score += 2
        if str(r.get("Status", "")):
            score += 1
    return score


def parse_interfaces_auto(interfaces_text: str) -> tuple[pd.DataFrame, str]:
    """Try all known CLI formats; pick the parse with the best score."""
    body = strip_nccm_header(interfaces_text)
    if not body.strip():
        return _empty_frame(), "empty"

    parsers: list[tuple[str, object]] = [
        ("cisco_interface_status", parse_cisco_interface_status_tokenized),
        ("cisco_ip_interface_brief", parse_cisco_ip_interface_brief),
        ("cisco_interface_summary", parse_cisco_interface_summary),
        ("huawei_interface_brief", parse_huawei_interface_brief),
        ("fortinet_interface_physical", parse_fortinet_interface_physical),
    ]

    best_df = _empty_frame()
    best_id = "unparsed"
    best_score = 0
    for pid, fn in parsers:
        df = fn(body)
        sc = _score_frame(df)
        if sc > best_score:
            best_score = sc
            best_df = df
            best_id = pid

    return best_df, best_id


def parse_interface_backup(
    vendor: str,
    interfaces_text: str | None,
    config_text: str | None = None,
) -> tuple[pd.DataFrame, str]:
    v = (vendor or "").strip().lower()
    if interfaces_text and interfaces_text.strip():
        df, parser_id = parse_interfaces_auto(interfaces_text)
        if not df.empty:
            return df, parser_id
        if v == "huawei":
            df = parse_huawei_interface_brief(interfaces_text)
            if not df.empty:
                return df, "huawei_interface_brief"
        if v in ("fortinet",):
            df = parse_fortinet_interface_physical(interfaces_text)
            if not df.empty:
                return df, "fortinet_interface_physical"

    if config_text and config_text.strip():
        return parse_interfaces_from_config(config_text), "config_interface_blocks"
    return _empty_frame(), "none"


def load_device_interface_table(
    device_path: str,
    vendor: str,
    snapshot: str | None = None,
) -> tuple[str | None, pd.DataFrame, str, str, str | None]:
    """Return ts, table, source_note, parser_id, raw_interfaces_text."""
    ts, snap_dir = latest_snapshot_dir(device_path)
    if snapshot:
        cand = os.path.join(device_path, snapshot)
        if os.path.isdir(cand):
            ts, snap_dir = snapshot, cand
    if not snap_dir:
        return None, _empty_frame(), "no backup", "none", None

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

    df, parser_id = parse_interface_backup(vendor, iface_text, config_text)
    if iface_text and not df.empty and parser_id != "config_interface_blocks":
        note = "interfaces.txt"
    elif config_text and not df.empty:
        note = "config.txt (interface blocks)"
    elif not os.path.isfile(iface_path):
        note = "missing interfaces.txt"
    elif iface_text and df.empty:
        note = "unparsed interfaces.txt"
    else:
        note = "interfaces.txt"
    return ts, df, note, parser_id, iface_text