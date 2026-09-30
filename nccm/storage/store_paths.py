"""Store path boundary checks — all file I/O under store_dir must pass through here."""
from __future__ import annotations

import os
from pathlib import Path

from nccm.config import store_dir


class SecurityError(ValueError):
    """Raised when a path escapes the configured store root."""


def resolve_inside_store(candidate: Path | str, *, strict_exists: bool = False) -> Path:
    root = store_dir().resolve(strict=True)
    target = Path(candidate).resolve(strict=strict_exists)
    if not target.is_relative_to(root):
        raise SecurityError(f"path outside store: {candidate!r}")
    if target.is_symlink():
        raise SecurityError(f"symlink not allowed in store path: {candidate!r}")
    return target


def resolve_snapshot_dir(snapshot_path: str | Path) -> Path:
    """Resolve a snapshot directory and ensure it stays inside the store."""
    return resolve_inside_store(Path(snapshot_path), strict_exists=False)


def resolve_snapshot_file(snapshot_path: str | Path, filename: str) -> Path:
    snap = resolve_snapshot_dir(snapshot_path)
    target = (snap / filename).resolve(strict=False)
    return resolve_inside_store(target, strict_exists=False)
