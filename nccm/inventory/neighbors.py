from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from nccm.config import store_dir
from nccm.parsers.cdp_lldp import (
    _register_hostname,
    make_device_key,
    neighbors_from_backup_snapshot,
    split_device_key,
)
from nccm.storage.index_db import (
    InventoryDisplayRow,
    list_inventory,
    list_inventory_display,
    list_snapshots_for_device,
)


def device_store_path(site: str, ip: str, hostname: str) -> Path:
    safe_host = re.sub(r"[^\w.\-]+", "_", (hostname or "").strip())[:64] or "unknown"
    return store_dir() / site / f"{ip}__{safe_host}"


def resolve_neighbor_context(
    device_key: str,
) -> tuple[
    InventoryDisplayRow | None,
    Any | None,
    Path,
    str,
    str,
    str,
]:
    """Map device_key (often stack display hostname) to logical store + parse hostname."""
    display_row: InventoryDisplayRow | None = None
    for dr in list_inventory_display():
        if make_device_key(dr.site, dr.ip, dr.hostname, dr.port) == device_key:
            display_row = dr
            break

    logical_by_id = {r.device_id: r for r in list_inventory()}
    logical = (
        logical_by_id.get(display_row.device_id) if display_row else None
    )

    if not logical:
        site, ip, host_part = split_device_key(device_key)
        logical = next(
            (
                x
                for x in list_inventory()
                if x.site == site and x.ip == ip and x.hostname == host_part
            ),
            None,
        )
        if not display_row and logical:
            display_row = next(
                (
                    dr
                    for dr in list_inventory_display()
                    if dr.device_id == logical.device_id
                    and make_device_key(dr.site, dr.ip, dr.hostname, dr.port)
                    == device_key
                ),
                None,
            )

    if logical:
        store = device_store_path(logical.site, logical.ip, logical.hostname)
        vendor = logical.vendor
        device_id = logical.device_id
        parse_hostname = display_row.hostname if display_row else logical.hostname
    else:
        site, ip, host_part = split_device_key(device_key)
        store = device_store_path(site, ip, host_part)
        vendor = display_row.vendor if display_row else ""
        device_id = display_row.device_id if display_row else ""
        parse_hostname = display_row.hostname if display_row else host_part

    return display_row, logical, store, parse_hostname, vendor, device_id


def build_hostname_lookup(rows: list[InventoryDisplayRow]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for r in rows:
        key = make_device_key(r.site, r.ip, r.hostname, r.port)
        _register_hostname(
            lookup, key, r.hostname, site=r.site, ip=r.ip, port=r.port
        )
    return lookup


def neighbor_device_rows(
    *,
    query: str = "",
    site: str = "",
    vendor: str = "",
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Expanded inventory (stack / HA per member) with neighbor stats from latest snapshot."""
    inv = list_inventory_display(query=query, site=site, vendor=vendor)
    lookup = build_hostname_lookup(inv)
    logical_by_id = {r.device_id: r for r in list_inventory()}
    out: list[dict[str, Any]] = []

    for r in inv:
        device_key = make_device_key(r.site, r.ip, r.hostname, r.port)
        snaps = list_snapshots_for_device(r.device_id)
        snap_path = snaps[0].snapshot_path if snaps else ""
        neighbor_rows, cdp_status, lldp_status = neighbors_from_backup_snapshot(
            snap_path or "",
            r.hostname,
            r.vendor,
            lookup,
        )
        log = logical_by_id.get(r.device_id)
        store_host = log.hostname if log else r.hostname
        out.append(
            {
                "device_key": device_key,
                "device_id": r.device_id,
                "site": r.site,
                "ip": r.ip,
                "port": r.port,
                "hostname": r.hostname,
                "vendor": r.vendor,
                "sw_version": r.sw_version,
                "model_summary": r.model_summary,
                "serial_summary": r.serial_summary,
                "stack_switch": r.stack_switch,
                "stack_role": r.stack_role,
                "cluster_type": r.cluster_type,
                "is_config_anchor": r.is_config_anchor,
                "neighbor_count": len(neighbor_rows),
                "cdp_status": cdp_status,
                "lldp_status": lldp_status,
                "store_path": str(device_store_path(r.site, r.ip, store_host)),
            }
        )
    return out, lookup


def neighbors_for_device(
    device_key: str,
    *,
    snapshot_ts: str = "",
    lookup: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], str, str, str]:
    """Return neighbor rows, cdp_status, lldp_status, version_label."""
    _display, logical, store, parse_hostname, vendor, device_id = resolve_neighbor_context(
        device_key
    )
    if lookup is None:
        lookup = build_hostname_lookup(list_inventory_display())

    snaps = list_snapshots_for_device(device_id) if device_id else []
    if snaps:
        snap = snaps[0]
        if snapshot_ts:
            for s in snaps:
                if snapshot_ts in (s.snapshot_path, s.created_at or ""):
                    snap = s
                    break
                base = os.path.basename(s.snapshot_path.rstrip("/"))
                if snapshot_ts == base:
                    snap = s
                    break
        snap_path = snap.snapshot_path
        rows, cdp, lldp = neighbors_from_backup_snapshot(
            snap_path, parse_hostname, vendor, lookup
        )
        label = os.path.basename(snap_path.rstrip("/")) or (snap.created_at or "—")
        return rows, cdp, lldp, label

    from nccm.parsers.cdp_lldp import list_device_backup_versions

    versions = list_device_backup_versions(str(store), limit=10)
    if not versions:
        return [], "missing", "missing", "—"
    ts = snapshot_ts if snapshot_ts in versions else versions[0]
    snap_root = store / "snapshots"
    base = snap_root if snap_root.is_dir() else store
    snap_path = os.path.join(str(base), ts)
    rows, cdp, lldp = neighbors_from_backup_snapshot(
        snap_path, parse_hostname, vendor, lookup
    )
    return rows, cdp, lldp, ts


def neighbor_display_rows(
    neighbor_rows: list[dict[str, Any]],
    lookup: dict[str, str],
) -> list[dict[str, str]]:
    inv_display = list_inventory_display()
    by_key = {
        make_device_key(r.site, r.ip, r.hostname, r.port): r for r in inv_display
    }

    def label(remote_key: str | None, remote_hostname: str) -> str:
        if remote_key and remote_key in by_key:
            r = by_key[remote_key]
            return f"{r.hostname} ({r.ip})"
        return remote_hostname

    return [
        {
            "local_interface": n["local_interface"],
            "protocol": n["protocol"],
            "remote_device": label(n.get("remote_device_key"), n["remote_hostname"]),
            "remote_port": n["remote_port"],
            "cable_type": n["cable_type"],
        }
        for n in neighbor_rows
    ]