from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NetDriverProfile:
    vendor: str
    model: str
    version: str


@dataclass(frozen=True)
class DeviceRow:
    site: str
    ip: str
    vendor: str
    model: str | None = None
    version: str | None = None
    hostname_hint: str | None = None
    port: int = 22


@dataclass
class BackupArtifact:
    name: str
    lines: int = 0


@dataclass
class BackupResult:
    site: str
    ip: str
    hostname: str
    status: str
    snapshot_dir: str | None = None
    error: str | None = None
    manifest: dict[str, Any] | None = None