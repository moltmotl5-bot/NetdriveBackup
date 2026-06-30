"""
Build CDP/LLDP neighbor tables from backup output (cdp.txt / lldp.txt).

Parses Cisco `show cdp neighbors` / `show lldp neighbors` table output
(single-line and two-line device-id formats).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

_IFACE_TOKEN = (
    r"(?:GigabitEthernet|TenGigabitEthernet|FastEthernet|Ethernet|"
    r"Gig|Gi|Ten|Te|Eth|Et|Fa)\s*[\d/]+"
)


@dataclass
class NeighborRecord:
    local_interface: str
    remote_hostname: str
    remote_port: str
    cable_type: str = "unknown"


def make_device_key(site: str, ip: str, hostname: str) -> str:
    return f"{site}|{ip}|{hostname}"


def split_device_key(device_key: str) -> tuple[str, str, str]:
    site, ip, hostname = device_key.split("|", 2)
    return site, ip, hostname


def normalize_hostname(name: str) -> str:
    base = name.split(".")[0] if name else ""
    return base.strip().lower()


def _clean_remote_device_id(raw: str) -> str:
    raw = re.sub(r"\([^)]*\)", "", raw).strip()
    if "." in raw:
        return raw.split(".")[0]
    return raw


def _classify_cable(local_port: str, remote_port: str) -> str:
    for port in (remote_port, local_port):
        p = port.replace(" ", "").lower()
        if p.startswith(("ten", "te")):
            return "fiber"
        if p.startswith(("gig", "gi")):
            return "gigabit"
        if p.startswith(("eth", "et")):
            return "ethernet"
        if p.startswith("fa"):
            return "fastethernet"
    return "unknown"


def _is_cdp_error(text: str) -> bool:
    if not text or not text.strip():
        return True
    head = text[:300]
    return "% Invalid" in head or head.lstrip().startswith("% ")


def _extract_iface_pair(line: str) -> tuple[str, str] | None:
    matches = re.findall(_IFACE_TOKEN, line, flags=re.IGNORECASE)
    if len(matches) < 2:
        return None
    return matches[0].strip(), matches[-1].strip()


def parse_show_cdp_neighbors(text: str, local_device: str) -> list[NeighborRecord]:
    """Parse `show cdp neighbors` brief/table output."""
    if _is_cdp_error(text):
        return []

    records: list[NeighborRecord] = []
    lines = text.replace("\r", "").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        lower = line.lower()
        if "capability" in lower and ("device id" in lower or "device-id" in lower):
            i += 1
            continue
        if lower.startswith("total cdp"):
            break

        # Two-line: device id then detail line
        if re.match(r"^[\w.-]+(?:\([^)]+\))?\s*$", line) and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            pair = _extract_iface_pair(next_line)
            if pair:
                local_port, remote_port = pair
                remote = _clean_remote_device_id(line)
                records.append(
                    NeighborRecord(
                        local_interface=local_port,
                        remote_hostname=remote,
                        remote_port=remote_port,
                        cable_type=_classify_cable(local_port, remote_port),
                    )
                )
                i += 2
                continue

        # Single-line row
        pair = _extract_iface_pair(line)
        if pair:
            parts = line.split(None, 1)
            if parts:
                remote = _clean_remote_device_id(parts[0])
                local_port, remote_port = pair
                records.append(
                    NeighborRecord(
                        local_interface=local_port,
                        remote_hostname=remote,
                        remote_port=remote_port,
                        cable_type=_classify_cable(local_port, remote_port),
                    )
                )
        i += 1

    return records


def parse_show_lldp_neighbors(text: str, local_device: str) -> list[NeighborRecord]:
    """Parse `show lldp neighbors` table output."""
    if not text or not text.strip():
        return []
    if "% Invalid" in text[:300]:
        return []

    records: list[NeighborRecord] = []
    lines = text.replace("\r", "").split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        lower = line.lower()
        if "capability" in lower and "device id" in lower:
            continue
        if lower.startswith("total lldp"):
            break

        # Typical: DeviceID  LocalIntf  Hold-time  Capability  PortID
        m = re.match(
            r"^(\S+)\s+((?:Gig|Gi|Ten|Te|Eth|Et|Fa)\S*[\d/]+)\s+\d+\s+\S+\s+(\S+)\s*$",
            line,
            re.IGNORECASE,
        )
        if m:
            remote = _clean_remote_device_id(m.group(1))
            local_port = m.group(2)
            remote_port = m.group(3)
            if not re.search(r"[\d/]", remote_port):
                remote_port = f"Port {remote_port}"
            records.append(
                NeighborRecord(
                    local_interface=local_port,
                    remote_hostname=remote,
                    remote_port=remote_port,
                    cable_type=_classify_cable(local_port, remote_port),
                )
            )
            continue

        pair = _extract_iface_pair(line)
        if pair and line.split():
            remote = _clean_remote_device_id(line.split()[0])
            local_port, remote_port = pair
            records.append(
                NeighborRecord(
                    local_interface=local_port,
                    remote_hostname=remote,
                    remote_port=remote_port,
                    cable_type=_classify_cable(local_port, remote_port),
                )
            )

    return records


def _register_hostname(hostname_lookup: dict[str, str], device_key: str, hostname: str) -> None:
    keys = {
        normalize_hostname(hostname),
        hostname.lower(),
        hostname.split(".")[0].lower(),
    }
    for k in keys:
        if k and k not in hostname_lookup:
            hostname_lookup[k] = device_key


def _resolve_remote_key(hostname_lookup: dict[str, str], remote_hostname: str) -> str | None:
    candidates = [
        normalize_hostname(remote_hostname),
        remote_hostname.lower(),
        remote_hostname.split(".")[0].lower(),
    ]
    for c in candidates:
        if c in hostname_lookup:
            return hostname_lookup[c]
    return None


def _latest_backup_dir(device_path: str) -> str | None:
    if not os.path.isdir(device_path):
        return None
    dates = sorted(
        [d for d in os.listdir(device_path) if os.path.isdir(os.path.join(device_path, d))],
        reverse=True,
    )
    return os.path.join(device_path, dates[0]) if dates else None


def _vendor_from_device_path(device_path: str) -> str:
    """Match build_inventory vendor detection from latest version_info.txt."""
    backup = _latest_backup_dir(device_path)
    if not backup:
        return "Unknown"
    version_file = os.path.join(backup, "version_info.txt")
    if not os.path.isfile(version_file):
        return "Unknown"
    with open(version_file, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    if "Cisco IOS Software" in content or "Cisco Nexus" in content or "NX-OS" in content:
        return "Cisco"
    if "VRP (R) software" in content or "Huawei" in content or "elabel" in content:
        return "Huawei"
    return "Unknown"


def build_neighbor_catalog(
    output_dir: str,
) -> tuple[pd.DataFrame, dict[str, str], dict[str, list[dict[str, Any]]]]:
    device_rows: list[dict[str, Any]] = []
    hostname_lookup: dict[str, str] = {}
    neighbors_by_key: dict[str, list[dict[str, Any]]] = {}

    if not os.path.isdir(output_dir):
        empty = pd.DataFrame(
            columns=[
                "device_key",
                "Site",
                "IP",
                "Hostname",
                "label",
                "neighbor_count",
                "cdp_status",
                "lldp_status",
            ]
        )
        return empty, hostname_lookup, neighbors_by_key

    for site in sorted(os.listdir(output_dir)):
        site_path = os.path.join(output_dir, site)
        if not os.path.isdir(site_path):
            continue

        for device_folder in sorted(os.listdir(site_path)):
            device_path = os.path.join(site_path, device_folder)
            if not os.path.isdir(device_path):
                continue

            match = re.match(r"([\d.]+)_(.+)", device_folder)
            if not match:
                continue

            ip = match.group(1)
            hostname = match.group(2)
            device_key = make_device_key(site, ip, hostname)
            _register_hostname(hostname_lookup, device_key, hostname)

            device_rows.append(
                {
                    "device_key": device_key,
                    "Site": site,
                    "IP": ip,
                    "Hostname": hostname,
                }
            )

    for row in device_rows:
        device_key = row["device_key"]
        site = row["Site"]
        hostname = row["Hostname"]
        device_path = os.path.join(output_dir, site, f"{row['IP']}_{hostname}")
        backup_path = _latest_backup_dir(device_path)
        vendor = _vendor_from_device_path(device_path)

        cdp_text = ""
        lldp_text = ""
        cdp_status = "missing"
        lldp_status = "missing"

        if backup_path:
            cdp_file = os.path.join(backup_path, "cdp.txt")
            lldp_file = os.path.join(backup_path, "lldp.txt")
            if os.path.isfile(cdp_file):
                with open(cdp_file, "r", encoding="utf-8", errors="replace") as f:
                    cdp_text = f.read()
                cdp_status = "error" if _is_cdp_error(cdp_text) else "ok"
            if os.path.isfile(lldp_file):
                with open(lldp_file, "r", encoding="utf-8", errors="replace") as f:
                    lldp_text = f.read()
                lldp_status = "error" if "% Invalid" in lldp_text[:300] else "ok"

        skip_lldp = vendor.lower() == "cisco" and cdp_status == "ok"
        if skip_lldp:
            lldp_status = "skipped"

        neighbor_rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()

        protocol_sources: list[tuple[str, Any, str]] = [
            ("CDP", parse_show_cdp_neighbors, cdp_text),
        ]
        if not skip_lldp:
            protocol_sources.append(("LLDP", parse_show_lldp_neighbors, lldp_text))

        for protocol, parser, text in protocol_sources:
            if not text.strip():
                continue
            for rec in parser(text, local_device=hostname):
                dedupe_key = (
                    protocol,
                    rec.local_interface,
                    rec.remote_hostname,
                    rec.remote_port,
                )
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)

                remote_device_key = _resolve_remote_key(hostname_lookup, rec.remote_hostname)
                neighbor_rows.append(
                    {
                        "local_interface": rec.local_interface,
                        "protocol": protocol,
                        "remote_hostname": rec.remote_hostname,
                        "remote_port": rec.remote_port,
                        "cable_type": rec.cable_type,
                        "remote_device_key": remote_device_key,
                    }
                )

        neighbors_by_key[device_key] = neighbor_rows
        row["cdp_status"] = cdp_status
        row["lldp_status"] = lldp_status
        row["neighbor_count"] = len(neighbor_rows)
        row["label"] = (
            f"[{site}] {hostname} ({ip}) · {len(neighbor_rows)} 鄰居"
            f" · CDP:{cdp_status} LLDP:{lldp_status}"
        )

    devices_df = pd.DataFrame(device_rows)
    if not devices_df.empty:
        devices_df = devices_df.sort_values(["Site", "Hostname"], kind="stable").reset_index(drop=True)

    return devices_df, hostname_lookup, neighbors_by_key


def neighbor_table_dataframe(neighbor_rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not neighbor_rows:
        return pd.DataFrame(
            columns=[
                "local_interface",
                "protocol",
                "remote_hostname",
                "remote_port",
                "cable_type",
            ]
        )
    return pd.DataFrame(neighbor_rows)[
        [
            "local_interface",
            "protocol",
            "remote_hostname",
            "remote_port",
            "cable_type",
        ]
    ].rename(
        columns={
            "local_interface": "本端介面",
            "protocol": "協定",
            "remote_hostname": "鄰居設備",
            "remote_port": "鄰居介面",
            "cable_type": "連線類型",
        }
    )