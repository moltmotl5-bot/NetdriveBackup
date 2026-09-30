"""Resolve inventory device_id to SwitchMap snapshot context."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nccm.inventory.neighbors import device_store_path
from nccm.parsers.cdp_lldp import list_device_backup_versions
from nccm.profiles import normalize_vendor
from nccm.storage.index_db import list_inventory, parse_device_id
from nccm.switchmap.log_builder import build_switchdraw_log, resolve_snapshot_path_for_device


@dataclass(frozen=True)
class SwitchmapDeviceContext:
    device_id: str
    site: str
    ip: str
    hostname: str
    vendor: str
    store_path: str
    snapshot_ts: str
    versions: tuple[str, ...]
    cisco_supported: bool
    log_result: Any | None = None
    error: str | None = None


def switchmap_context_for_device(
    device_id: str,
    *,
    snapshot_ts: str = "",
) -> SwitchmapDeviceContext:
    site, ip, _port, _host = parse_device_id(device_id)
    inv = list_inventory()
    row = next((r for r in inv if r.device_id == device_id), None)
    if not row:
        row = next((r for r in inv if r.site == site and r.ip == ip), None)
    if not row:
        return SwitchmapDeviceContext(
            device_id=device_id,
            site=site,
            ip=ip,
            hostname="",
            vendor="",
            store_path="",
            snapshot_ts="",
            versions=(),
            cisco_supported=False,
            error="找不到設備",
        )

    vendor = normalize_vendor(row.vendor)
    cisco = vendor == "cisco"
    store = str(device_store_path(row.site, row.ip, row.hostname))
    versions = tuple(list_device_backup_versions(store, limit=10))
    ts = snapshot_ts if snapshot_ts in versions else (versions[0] if versions else "")

    if not cisco:
        return SwitchmapDeviceContext(
            device_id=row.device_id,
            site=row.site,
            ip=row.ip,
            hostname=row.hostname,
            vendor=row.vendor,
            store_path=store,
            snapshot_ts=ts,
            versions=versions,
            cisco_supported=False,
            error="SwitchMap 目前僅支援 Cisco IOS / IOS-XE 設備。",
        )

    if not ts:
        return SwitchmapDeviceContext(
            device_id=row.device_id,
            site=row.site,
            ip=row.ip,
            hostname=row.hostname,
            vendor=row.vendor,
            store_path=store,
            snapshot_ts="",
            versions=versions,
            cisco_supported=True,
            error="尚無備份快照，請先執行備份。",
        )

    snap = resolve_snapshot_path_for_device(store, ts)
    if snap is None:
        return SwitchmapDeviceContext(
            device_id=row.device_id,
            site=row.site,
            ip=row.ip,
            hostname=row.hostname,
            vendor=row.vendor,
            store_path=store,
            snapshot_ts=ts,
            versions=versions,
            cisco_supported=True,
            error="快照目錄不存在。",
        )

    log_result = build_switchdraw_log(snap, prompt_hostname=row.hostname)
    return SwitchmapDeviceContext(
        device_id=row.device_id,
        site=row.site,
        ip=row.ip,
        hostname=row.hostname,
        vendor=row.vendor,
        store_path=store,
        snapshot_ts=log_result.snapshot_ts,
        versions=versions,
        cisco_supported=True,
        log_result=log_result,
    )
