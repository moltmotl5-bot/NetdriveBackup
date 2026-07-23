"""Snapshot retention: keep newest N per device (existing versioning dirs)."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from nccm.storage.index_db import connect


@dataclass(frozen=True)
class RetentionCandidate:
    device_id: str
    snapshot_id: int
    snapshot_path: str
    created_at: str


@dataclass(frozen=True)
class RetentionPlan:
    keep_last: int
    candidates: list[RetentionCandidate]
    dry_run: bool


def plan_retention(*, keep_last: int = 10, device_id: str | None = None) -> RetentionPlan:
    keep = max(1, int(keep_last))
    sql = """
        SELECT id, device_id, snapshot_path, created_at
        FROM snapshots
        WHERE status = 'ok'
    """
    args: list = []
    if device_id:
        sql += " AND device_id = ?"
        args.append(device_id)
    sql += " ORDER BY device_id, created_at DESC"
    by_dev: dict[str, list[RetentionCandidate]] = {}
    with connect() as conn:
        for r in conn.execute(sql, args).fetchall():
            did = str(r["device_id"])
            by_dev.setdefault(did, []).append(
                RetentionCandidate(
                    device_id=did,
                    snapshot_id=int(r["id"]),
                    snapshot_path=str(r["snapshot_path"]),
                    created_at=str(r["created_at"] or ""),
                )
            )
    doomed: list[RetentionCandidate] = []
    for _did, rows in by_dev.items():
        if len(rows) <= keep:
            continue
        doomed.extend(rows[keep:])
    return RetentionPlan(keep_last=keep, candidates=doomed, dry_run=True)


def _refresh_device_aggregates(conn, device_ids: set[str]) -> None:
    for did in device_ids:
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
        count_row = conn.execute(
            "SELECT COUNT(*) AS c FROM snapshots WHERE device_id = ? AND status = 'ok'",
            (did,),
        ).fetchone()
        snap_count = int(count_row["c"]) if count_row else 0
        if not latest:
            conn.execute("DELETE FROM devices WHERE device_id = ?", (did,))
            conn.execute("DELETE FROM stack_units WHERE device_id = ?", (did,))
            continue
        conn.execute(
            """
            UPDATE devices SET
                snapshot_count = ?,
                latest_snapshot_id = ?,
                latest_snapshot_at = ?,
                hostname = ?,
                vendor = ?,
                sw_version = ?,
                model_summary = ?,
                serial_summary = ?
            WHERE device_id = ?
            """,
            (
                snap_count,
                int(latest["id"]),
                latest["created_at"],
                latest["hostname"] or "",
                latest["vendor"] or "",
                latest["sw_version"] or "",
                latest["model_summary"] or "",
                latest["serial_summary"] or "",
                did,
            ),
        )


def apply_retention(plan: RetentionPlan, *, dry_run: bool = True) -> dict:
    """Delete snapshot dirs + DB rows beyond keep_last. Always keeps ≥1 per device via plan."""
    deleted: list[str] = []
    skipped: list[str] = []
    if dry_run:
        return {
            "dry_run": True,
            "keep_last": plan.keep_last,
            "would_delete": len(plan.candidates),
            "paths": [c.snapshot_path for c in plan.candidates],
        }
    ids = [c.snapshot_id for c in plan.candidates]
    device_ids = {c.device_id for c in plan.candidates}
    for c in plan.candidates:
        p = Path(c.snapshot_path)
        try:
            if p.is_dir():
                shutil.rmtree(p)
                deleted.append(str(p))
            else:
                skipped.append(str(p))
        except OSError:
            skipped.append(str(p))
    if ids:
        placeholders = ",".join("?" * len(ids))
        with connect() as conn:
            conn.execute(f"DELETE FROM snapshots WHERE id IN ({placeholders})", ids)
            _refresh_device_aggregates(conn, device_ids)
    return {
        "dry_run": False,
        "keep_last": plan.keep_last,
        "deleted": len(deleted),
        "skipped": skipped,
        "paths": deleted,
    }
