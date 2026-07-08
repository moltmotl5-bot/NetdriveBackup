from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from nccm.config import store_dir
from nccm.profiles import normalize_vendor
from nccm.parsers.stack import config_anchor_unit, parse_cisco_stack_units
from nccm.parsers.version import parse_version_info
from nccm.storage.writer import safe_hostname

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    site TEXT NOT NULL,
    ip TEXT NOT NULL,
    hostname TEXT,
    vendor TEXT,
    sw_version TEXT,
    model_summary TEXT,
    serial_summary TEXT,
    snapshot_count INTEGER NOT NULL DEFAULT 0,
    latest_snapshot_id INTEGER,
    latest_snapshot_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    run_id TEXT,
    site TEXT NOT NULL,
    ip TEXT NOT NULL,
    hostname TEXT,
    vendor TEXT,
    sw_version TEXT,
    model_summary TEXT,
    serial_summary TEXT,
    snapshot_path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    netdriver_json TEXT,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_device ON snapshots(device_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_devices_site ON devices(site);
CREATE INDEX IF NOT EXISTS idx_devices_vendor ON devices(vendor);

CREATE TABLE IF NOT EXISTS stack_units (
    unit_id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    switch_num INTEGER NOT NULL,
    role TEXT,
    model TEXT,
    serial TEXT,
    sw_version TEXT,
    hostname TEXT,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);
CREATE INDEX IF NOT EXISTS idx_stack_units_device ON stack_units(device_id, switch_num);
"""


def db_path() -> Path:
    return store_dir() / "index.db"


def device_id(site: str, ip: str, port: int = 22, hostname: str = "") -> str:
    """Logical backup target; includes hostname to avoid duplicate IP collisions."""
    host = safe_hostname(hostname) if (hostname or "").strip() else "unknown"
    return f"{site}::{ip}::{int(port)}::{host}"


def parse_device_id(device_id_value: str) -> tuple[str, str, int, str]:
    parts = device_id_value.split("::")
    if len(parts) == 2:
        return parts[0], parts[1], 22, ""
    if len(parts) == 3:
        if parts[2].isdigit():
            return parts[0], parts[1], int(parts[2]), ""
        return parts[0], parts[1], 22, parts[2]
    if len(parts) >= 4:
        return parts[0], parts[1], int(parts[2]), parts[3]
    raise ValueError(f"invalid device_id: {device_id_value!r}")


def infer_ssh_port(manifest: dict[str, Any]) -> int:
    """Port for index key; lab 127.0.0.1 multi-mock needs disambiguation."""
    raw = manifest.get("port")
    if raw is not None and str(raw).strip() != "":
        return int(raw)
    ip = str(manifest.get("ip") or "")
    vendor = str(manifest.get("vendor") or "").lower()
    nd = manifest.get("netdriver") or {}
    if not vendor:
        vendor = str(nd.get("vendor") or "").lower()
    host = str(manifest.get("hostname") or "").lower()
    if ip == "127.0.0.1":
        if vendor == "cisco" or "nxos" in host or "nexus" in host:
            return 18020
        if vendor == "fortinet" or "forti" in host:
            return 18037
        if vendor == "huawei" or host in ("ce", "huawei_ce") or "huawei" in host:
            return 18038
    return 22


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


@dataclass(frozen=True)
class InventoryDisplayRow:
    """One table row; stack members share device_id (virtual-IP config anchor)."""

    device_id: str
    site: str
    ip: str
    port: int
    hostname: str
    vendor: str
    sw_version: str
    model_summary: str
    serial_summary: str
    snapshot_count: int | None
    stack_switch: int | None
    stack_role: str
    is_config_anchor: bool


@dataclass(frozen=True)
class InventoryRow:
    device_id: str
    site: str
    ip: str
    port: int
    hostname: str
    vendor: str
    sw_version: str
    model_summary: str
    serial_summary: str
    snapshot_count: int
    latest_snapshot_id: int | None
    latest_snapshot_at: str | None


@dataclass(frozen=True)
class SnapshotRow:
    id: int
    device_id: str
    hostname: str
    created_at: str
    snapshot_path: str
    sw_version: str
    status: str


def _read_version_text(snap_dir: Path) -> str:
    vf = snap_dir / "version_info.txt"
    if not vf.is_file():
        return ""
    return vf.read_text(encoding="utf-8", errors="replace")


def _read_ha_status(snap_dir: Path) -> str:
    f = snap_dir / "ha_status.txt"
    if f.is_file():
        return f.read_text(encoding="utf-8", errors="replace")
    return ""

def _sync_stack_units(
    conn: sqlite3.Connection,
    did: str,
    vendor: str,
    version_text: str,
    ha_text: str = "",
) -> None:
    conn.execute("DELETE FROM stack_units WHERE device_id = ?", (did,))
    v = normalize_vendor(vendor)
    if v == "cisco":
        units = parse_cisco_stack_units(version_text)
    elif v == "fortinet":
        units = parse_fortigate_ha_units(ha_text or version_text)
    else:
        return
    if len(units) < 2:
        return
    for u in units:
        uid = f"{did}::sw::{u.switch_num}"
        conn.execute(
            """
            INSERT INTO stack_units (
                unit_id, device_id, switch_num, role, model, serial, sw_version, hostname
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                did,
                u.switch_num,
                u.role,
                u.model,
                u.serial,
                u.sw_version,
                u.hostname or "",
            ),
        )


def _read_version_from_snapshot(snap_dir: Path, vendor: str) -> Any:
    vf = snap_dir / "version_info.txt"
    if not vf.is_file():
        return parse_version_info("", vendor)
    return parse_version_info(vf.read_text(encoding="utf-8", errors="replace"), vendor)


def index_manifest(manifest: dict[str, Any], snapshot_path: Path) -> int:
    """Insert snapshot row and refresh device aggregate. Returns snapshot id."""
    site = manifest["site"]
    ip = manifest["ip"]
    hostname = manifest.get("hostname") or "unknown"
    vendor = manifest.get("vendor") or "unknown"

    # Backfill hostname from saved running-config (config.txt) if it was "unknown" at backup time
    if not hostname or str(hostname).lower() == "unknown":
        cfg_file = snapshot_path / "config.txt"
        if cfg_file.is_file():
            try:
                cfg_text = cfg_file.read_text(encoding="utf-8", errors="replace")
                from nccm.profiles import hostname_from_output
                better = hostname_from_output(vendor, cfg_text)
                if better and better != "unknown":
                    hostname = better
            except Exception:
                pass

    created_at = manifest.get("created_at") or ""
    status = manifest.get("status") or "ok"
    run_id = manifest.get("run_id") or ""
    nd = manifest.get("netdriver") or {}
    nd_json = json.dumps(nd, ensure_ascii=False)

    vf = _read_version_from_snapshot(snapshot_path, vendor)
    port = infer_ssh_port(manifest)
    did = device_id(site, ip, port, hostname)
    version_text = _read_version_text(snapshot_path)

    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO snapshots (
                device_id, run_id, site, ip, hostname, vendor, sw_version,
                model_summary, serial_summary, snapshot_path, created_at, status, netdriver_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_path) DO UPDATE SET
                hostname=excluded.hostname,
                vendor=excluded.vendor,
                sw_version=excluded.sw_version,
                model_summary=excluded.model_summary,
                serial_summary=excluded.serial_summary,
                status=excluded.status,
                netdriver_json=excluded.netdriver_json
            """,
            (
                did,
                run_id,
                site,
                ip,
                hostname,
                vf.vendor_label if vf.vendor_label != "Unknown" else vendor,
                vf.sw_version,
                vf.models,
                vf.serials,
                str(snapshot_path.resolve()),
                created_at,
                status,
                nd_json,
            ),
        )
        snap_id = cur.lastrowid
        if snap_id is None:
            row = conn.execute(
                "SELECT id FROM snapshots WHERE snapshot_path = ?",
                (str(snapshot_path.resolve()),),
            ).fetchone()
            snap_id = int(row["id"]) if row else 0

        count_row = conn.execute(
            "SELECT COUNT(*) AS c FROM snapshots WHERE device_id = ? AND status = 'ok'",
            (did,),
        ).fetchone()
        snap_count = int(count_row["c"]) if count_row else 0

        latest = conn.execute(
            """
            SELECT id, created_at, hostname, vendor, sw_version, model_summary, serial_summary
            FROM snapshots
            WHERE device_id = ? AND status = 'ok'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (did,),
        ).fetchone()

        if latest:
            conn.execute(
                """
                INSERT INTO devices (
                    device_id, site, ip, hostname, vendor, sw_version,
                    model_summary, serial_summary, snapshot_count,
                    latest_snapshot_id, latest_snapshot_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    hostname=excluded.hostname,
                    vendor=excluded.vendor,
                    sw_version=excluded.sw_version,
                    model_summary=excluded.model_summary,
                    serial_summary=excluded.serial_summary,
                    snapshot_count=excluded.snapshot_count,
                    latest_snapshot_id=excluded.latest_snapshot_id,
                    latest_snapshot_at=excluded.latest_snapshot_at,
                    updated_at=excluded.updated_at
                """,
                (
                    did,
                    site,
                    ip,
                    latest["hostname"],
                    latest["vendor"],
                    latest["sw_version"],
                    latest["model_summary"],
                    latest["serial_summary"],
                    snap_count,
                    latest["id"],
                    latest["created_at"],
                    created_at,
                ),
            )
        ha_text = _read_ha_status(snapshot_path) if normalize_vendor(vendor) == "fortinet" else ""
        _sync_stack_units(conn, did, vendor, version_text, ha_text)
        return int(snap_id)


def index_snapshot_dir(snapshot_path: Path) -> int:
    mf = snapshot_path / "manifest.json"
    if not mf.is_file():
        raise FileNotFoundError(mf)
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    return index_manifest(manifest, snapshot_path)


def rebuild_index() -> tuple[int, int]:
    """Scan store for manifest.json files. Returns (devices, snapshots)."""
    root = store_dir()
    snap_paths: list[Path] = []
    if root.is_dir():
        for mf in root.rglob("manifest.json"):
            snap_paths.append(mf.parent)
    snap_paths.sort()
    with connect() as conn:
        conn.execute("DELETE FROM snapshots")
        conn.execute("DELETE FROM stack_units")
        conn.execute("DELETE FROM devices")
    for sp in snap_paths:
        try:
            index_snapshot_dir(sp)
        except Exception:
            continue
    with connect() as conn:
        d = conn.execute("SELECT COUNT(*) AS c FROM devices").fetchone()
        s = conn.execute("SELECT COUNT(*) AS c FROM snapshots").fetchone()
        return int(d["c"]), int(s["c"])


def list_inventory(
    *,
    query: str = "",
    site: str = "",
    vendor: str = "",
    limit: int = 500,
) -> list[InventoryRow]:
    clauses = ["1=1"]
    params: list[Any] = []
    if query.strip():
        q = f"%{query.strip()}%"
        clauses.append(
            "(ip LIKE ? OR hostname LIKE ? OR model_summary LIKE ? OR serial_summary LIKE ?)"
        )
        params.extend([q, q, q, q])
    if site.strip():
        clauses.append("site = ?")
        params.append(site.strip())
    if vendor.strip():
        clauses.append("LOWER(vendor) LIKE ?")
        params.append(f"%{vendor.strip().lower()}%")

    sql = f"""
        SELECT device_id, site, ip, hostname, vendor, sw_version, model_summary,
               serial_summary, snapshot_count, latest_snapshot_id, latest_snapshot_at
        FROM devices
        WHERE {' AND '.join(clauses)}
        ORDER BY site, ip, device_id
        LIMIT ?
    """
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        InventoryRow(
            device_id=r["device_id"],
            site=r["site"],
            ip=r["ip"],
            port=parse_device_id(r["device_id"])[2],
            hostname=r["hostname"] or "",
            vendor=r["vendor"] or "",
            sw_version=r["sw_version"] or "",
            model_summary=r["model_summary"] or "",
            serial_summary=r["serial_summary"] or "",
            snapshot_count=int(r["snapshot_count"] or 0),
            latest_snapshot_id=r["latest_snapshot_id"],
            latest_snapshot_at=r["latest_snapshot_at"],
        )
        for r in rows
    ]


def list_inventory_display(
    *,
    query: str = "",
    site: str = "",
    vendor: str = "",
    limit: int = 500,
) -> list[InventoryDisplayRow]:
    """Expand stacks / HA clusters into one row per member; config stays on anchor."""
    from nccm.parsers.stack import StackUnit, config_anchor_unit
    from nccm.profiles import normalize_vendor

    logical = list_inventory(query=query, site=site, vendor=vendor, limit=limit)
    out: list[InventoryDisplayRow] = []
    with connect() as conn:
        for r in logical:
            su_rows = conn.execute(
                """
                SELECT switch_num, role, model, serial, sw_version, hostname
                FROM stack_units WHERE device_id = ?
                ORDER BY switch_num
                """,
                (r.device_id,),
            ).fetchall()
            if len(su_rows) >= 2:
                units = [
                    StackUnit(
                        int(x["switch_num"]),
                        x["role"] or "Member",
                        x["model"] or "",
                        x["serial"] or "",
                        x["sw_version"] or "",
                        x.get("hostname") or "",
                    )
                    for x in su_rows
                ]
                anchor = config_anchor_unit(units)
                anchor_num = anchor.switch_num if anchor else units[0].switch_num
                display_units = sorted(
                    su_rows,
                    key=lambda x: (
                        0 if int(x["switch_num"]) == anchor_num else 1,
                        int(x["switch_num"]),
                    ),
                )
                for x in display_units:
                    member_hostname = (x.get("hostname") or "").strip() or r.hostname
                    sn = int(x["switch_num"])
                    is_anchor = sn == anchor_num
                    out.append(
                        InventoryDisplayRow(
                            device_id=r.device_id,
                            site=r.site,
                            ip=r.ip,
                            port=r.port,
                            hostname=member_hostname,
                            vendor=r.vendor,
                            sw_version=(x["sw_version"] or r.sw_version),
                            model_summary=x["model"] or r.model_summary,
                            serial_summary=x["serial"] or "",
                            snapshot_count=r.snapshot_count if is_anchor else None,
                            stack_switch=sn,
                            stack_role=x["role"] or "Member",
                            is_config_anchor=is_anchor,
                        )
                    )
            else:
                out.append(
                    InventoryDisplayRow(
                        device_id=r.device_id,
                        site=r.site,
                        ip=r.ip,
                        port=r.port,
                        hostname=r.hostname,
                        vendor=r.vendor,
                        sw_version=r.sw_version,
                        model_summary=r.model_summary,
                        serial_summary=r.serial_summary,
                        snapshot_count=r.snapshot_count,
                        stack_switch=None,
                        stack_role="—",
                        is_config_anchor=True,
                    )
                )
    return out

def list_sites() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT site FROM devices ORDER BY site"
        ).fetchall()
    return [r["site"] for r in rows]


def list_snapshots_for_device(device_id_value: str) -> list[SnapshotRow]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, device_id, hostname, created_at, snapshot_path, sw_version, status
            FROM snapshots
            WHERE device_id = ? AND status = 'ok'
            ORDER BY created_at DESC
            """,
            (device_id_value,),
        ).fetchall()
    return [
        SnapshotRow(
            id=int(r["id"]),
            device_id=r["device_id"],
            hostname=r["hostname"] or "",
            created_at=r["created_at"],
            snapshot_path=r["snapshot_path"],
            sw_version=r["sw_version"] or "",
            status=r["status"],
        )
        for r in rows
    ]


def get_snapshot(snapshot_id: int) -> SnapshotRow | None:
    with connect() as conn:
        r = conn.execute(
            """
            SELECT id, device_id, hostname, created_at, snapshot_path, sw_version, status
            FROM snapshots WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone()
    if not r:
        return None
    return SnapshotRow(
        id=int(r["id"]),
        device_id=r["device_id"],
        hostname=r["hostname"] or "",
        created_at=r["created_at"],
        snapshot_path=r["snapshot_path"],
        sw_version=r["sw_version"] or "",
        status=r["status"],
    )


def read_config_text(snapshot_id: int, max_chars: int = 200_000) -> str:
    snap = get_snapshot(snapshot_id)
    if not snap:
        return ""
    path = Path(snap.snapshot_path) / "config.txt"
    if not path.is_file():
        return "(此版本無 config.txt)"
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n…(已截斷，請至 store 目錄查看完整檔案)…"
    return text