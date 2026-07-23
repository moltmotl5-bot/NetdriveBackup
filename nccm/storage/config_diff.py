"""Unified config.txt diff between two snapshots (stdlib difflib)."""
from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass
from pathlib import Path

from nccm.storage.index_db import get_snapshot, list_snapshots_for_device


@dataclass(frozen=True)
class ConfigDiffResult:
    device_id: str
    a_id: int
    b_id: int
    a_label: str
    b_label: str
    identical: bool
    unified: str
    a_hash: str
    b_hash: str


def config_sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


def read_snapshot_config(snapshot_id: int) -> tuple[str, str]:
    """Return (text, label). Empty text if missing."""
    snap = get_snapshot(snapshot_id)
    if not snap:
        return "", ""
    path = Path(snap.snapshot_path) / "config.txt"
    label = f"{snap.created_at} (#{snap.id})"
    if not path.is_file():
        return "", label
    return path.read_text(encoding="utf-8", errors="replace"), label


def diff_configs(
    text_a: str,
    text_b: str,
    *,
    fromfile: str = "a",
    tofile: str = "b",
    context: int = 3,
) -> str:
    a_lines = (text_a or "").splitlines(keepends=True)
    b_lines = (text_b or "").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(a_lines, b_lines, fromfile=fromfile, tofile=tofile, n=context)
    )


def diff_snapshots(device_id: str, a_id: int, b_id: int, *, context: int = 3) -> ConfigDiffResult:
    if a_id <= 0 or b_id <= 0:
        raise ValueError("snapshot ids required")
    if a_id == b_id:
        raise ValueError("select two different snapshots")
    sa = get_snapshot(a_id)
    sb = get_snapshot(b_id)
    if not sa or not sb:
        raise ValueError("snapshot not found")
    if device_id and (sa.device_id != device_id or sb.device_id != device_id):
        raise ValueError("snapshot does not belong to device")
    text_a, label_a = read_snapshot_config(a_id)
    text_b, label_b = read_snapshot_config(b_id)
    ha, hb = config_sha256(text_a), config_sha256(text_b)
    unified = diff_configs(text_a, text_b, fromfile=label_a, tofile=label_b, context=context)
    return ConfigDiffResult(
        device_id=sa.device_id,
        a_id=a_id,
        b_id=b_id,
        a_label=label_a,
        b_label=label_b,
        identical=ha == hb,
        unified=unified or "(no textual differences)\n",
        a_hash=ha[:12],
        b_hash=hb[:12],
    )


def latest_two_changed(device_id: str) -> tuple[int, int] | None:
    """If newest two configs differ, return (older_id, newer_id)."""
    snaps = list_snapshots_for_device(device_id)
    if len(snaps) < 2:
        return None
    newer, older = snaps[0], snaps[1]
    ta, _ = read_snapshot_config(older.id)
    tb, _ = read_snapshot_config(newer.id)
    if config_sha256(ta) == config_sha256(tb):
        return None
    return older.id, newer.id
