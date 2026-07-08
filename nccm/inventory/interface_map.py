from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from nccm.inventory.neighbors import device_store_path
from nccm.parsers import interface_map
from nccm.parsers.cdp_lldp import list_device_backup_versions
from nccm.storage.index_db import list_inventory, parse_device_id


def interface_map_for_device(
    device_id: str,
    *,
    snapshot_ts: str = "",
) -> dict[str, Any]:
    """device_id = site::ip::port from index_db."""
    site, ip, _port, _host = parse_device_id(device_id)
    inv = list_inventory()
    row = next((r for r in inv if r.device_id == device_id), None)
    if not row:
        row = next((r for r in inv if r.site == site and r.ip == ip), None)
    if not row:
        return {"error": "device not found"}
    store = str(device_store_path(row.site, row.ip, row.hostname))
    versions = list_device_backup_versions(store, limit=10)
    ts = snapshot_ts if snapshot_ts in versions else (versions[0] if versions else "")
    ts_loaded, df, note, parser, _iface, snippets = interface_map.load_device_interface_table(
        store,
        row.vendor,
        snapshot=ts or None,
    )
    ports: list[dict[str, str]] = []
    if df is not None and not df.empty:
        ports = df.to_dict(orient="records")
    return {
        "site": row.site,
        "ip": row.ip,
        "hostname": row.hostname,
        "vendor": row.vendor,
        "versions": versions,
        "snapshot_ts": ts_loaded or ts,
        "source_note": note,
        "status_parser": parser,
        "ports": ports,
        "config_snippets": snippets,
    }