"""Snapshot retention: keep newest N per device (existing versioning dirs)."""
from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from nccm.storage.index_db import connect
from nccm.storage.store_paths import SecurityError, resolve_snapshot_dir

MIN_KEEP_LAST = 1
MAX_KEEP_LAST = 500
MAX_DELETE_PER_RUN = int(os.environ.get("NCCM_RETENTION_MAX_DELETE", "500"))
TOKEN_TTL_SECONDS = 300

_TOKENS: dict[str, tuple[float, str]] = {}


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


class RetentionError(ValueError):
    pass


def _plan_fingerprint(*, keep_last: int, device_id: str | None, candidates: list[RetentionCandidate]) -> str:
    parts = [
        str(keep_last),
        device_id or "",
        str(len(candidates)),
    ]
    for c in sorted(candidates, key=lambda x: (x.device_id, x.snapshot_id)):
        parts.append(f"{c.snapshot_id}:{c.snapshot_path}")
    raw = "\n".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _purge_expired_tokens(now: float | None = None) -> None:
    ts = now if now is not None else time.time()
    expired = [k for k, (exp, _fp) in _TOKENS.items() if exp <= ts]
    for k in expired:
        _TOKENS.pop(k, None)


def issue_retention_token(plan: RetentionPlan, *, device_id: str | None) -> str:
    _purge_expired_tokens()
    fp = _plan_fingerprint(
        keep_last=plan.keep_last,
        device_id=device_id,
        candidates=plan.candidates,
    )
    token = secrets.token_urlsafe(32)
    _TOKENS[token] = (time.time() + TOKEN_TTL_SECONDS, fp)
    return token


def consume_retention_token(
    token: str,
    *,
    keep_last: int,
    device_id: str | None,
    candidates: list[RetentionCandidate],
) -> None:
    _purge_expired_tokens()
    entry = _TOKENS.pop(token, None)
    if not entry:
        raise RetentionError("confirm token invalid or expired")
    expires, fp = entry
    if time.time() > expires:
        raise RetentionError("confirm token expired")
    expected = _plan_fingerprint(keep_last=keep_last, device_id=device_id, candidates=candidates)
    if not secrets.compare_digest(fp, expected):
        raise RetentionError("retention plan changed since dry-run; preview again")


def plan_retention(*, keep_last: int = 10, device_id: str | None = None) -> RetentionPlan:
    keep = max(MIN_KEEP_LAST, min(MAX_KEEP_LAST, int(keep_last)))
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
    if len(doomed) > MAX_DELETE_PER_RUN:
        raise RetentionError(
            f"would delete {len(doomed)} snapshots; max per run is {MAX_DELETE_PER_RUN}"
        )
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


def apply_retention(
    plan: RetentionPlan,
    *,
    dry_run: bool = True,
    confirm_token: str | None = None,
    device_id: str | None = None,
) -> dict:
    """Delete snapshot dirs + DB rows beyond keep_last. Always keeps ≥1 per device via plan."""
    if not dry_run:
        if not confirm_token:
            raise RetentionError("confirm_token required for retention delete")
        consume_retention_token(
            confirm_token,
            keep_last=plan.keep_last,
            device_id=device_id,
            candidates=plan.candidates,
        )
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
        try:
            p = resolve_snapshot_dir(c.snapshot_path)
        except SecurityError:
            skipped.append(c.snapshot_path)
            continue
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
