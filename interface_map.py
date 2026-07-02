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


def parse_cisco_interface_status(text: str) -> pd.DataFrame:
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
        if not started:
            if "Vlan" in raw and "Speed" in raw and "Port" in raw:
                started = True
                continue
        if re.match(r"^[-=]{3,}", raw):
            continue
        cols = re.split(r"\s{2,}", raw.strip())
        if len(cols) < 4:
            continue
        port = cols[0]
        if port.lower() in ("port", "interface"):
            continue
        if len(cols) >= 7:
            name, status, vlan, _duplex, speed, typ = (
                cols[1],
                cols[2],
                cols[3],
                cols[4],
                cols[5],
                cols[6],
            )
        elif len(cols) == 6:
            name, status, vlan, speed, typ = cols[1], cols[2], cols[3], cols[4], cols[5]
        elif len(cols) == 5:
            name, status, vlan, speed = cols[1], cols[2], cols[3], cols[4]
            typ = ""
        else:
            name, status, vlan = cols[1], cols[2], cols[3]
            speed, typ = "", ""
        rows.append(_row(port, name, status, vlan, speed, typ))
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
                rows.append(_row(current_if, desc, "", "", "", ""))
            current_if = m.group(1)
            desc = ""
            continue
        if current_if:
            dm = re.match(r"^\s*description\s+(.+)", line, re.I)
            if dm:
                desc = dm.group(1).strip()
    if current_if:
        rows.append(_row(current_if, desc, "", "", "", ""))
    return pd.DataFrame(rows, columns=INTERFACE_COLUMNS) if rows else _empty_frame()


def parse_interface_backup(
    vendor: str,
    interfaces_text: str | None,
    config_text: str | None = None,
) -> pd.DataFrame:
    v = (vendor or "").strip().lower()
    if interfaces_text and interfaces_text.strip():
        body = strip_nccm_header(interfaces_text)
        if v in ("cisco",):
            df = parse_cisco_interface_status(body)
            if not df.empty:
                return df
        if v == "huawei":
            df = parse_huawei_interface_brief(body)
            if not df.empty:
                return df
        if v in ("fortinet",):
            df = parse_fortinet_interface_physical(body)
            if not df.empty:
                return df
        df = parse_cisco_interface_status(body)
        if not df.empty:
            return df
    if config_text and config_text.strip():
        return parse_interfaces_from_config(config_text)
    return _empty_frame()


def load_device_interface_table(
    device_path: str,
    vendor: str,
    snapshot: str | None = None,
) -> tuple[str | None, pd.DataFrame, str]:
    ts, snap_dir = latest_snapshot_dir(device_path)
    if snapshot:
        cand = os.path.join(device_path, snapshot)
        if os.path.isdir(cand):
            ts, snap_dir = snapshot, cand
    if not snap_dir:
        return None, _empty_frame(), "no backup"

    iface_path = os.path.join(snap_dir, "interfaces.txt")
    config_path = os.path.join(snap_dir, "config.txt")
    iface_text = None
    config_text = None
    if os.path.isfile(iface_path):
        with open(iface_path, encoding="utf-8", errors="replace") as f:
            iface_text = f.read()
    if os.path.isfile(config_path):
        with open(config_path, encoding="utf-8", errors="replace") as f:
            config_text = f.read()

    df = parse_interface_backup(vendor, iface_text, config_text)
    if iface_text and not df.empty:
        note = "interfaces.txt"
    elif config_text and not df.empty:
        note = "config.txt (interface blocks)"
    elif not os.path.isfile(iface_path):
        note = "missing interfaces.txt"
    else:
        note = "unparsed interfaces.txt"
    return ts, df, note