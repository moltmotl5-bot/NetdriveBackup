from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from nccm.config import store_dir


def snapshot_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def safe_hostname(name: str) -> str:
    s = re.sub(r"[^\w.\-]+", "_", (name or "unknown").strip())
    return s[:64] or "unknown"


def device_base(site: str, ip: str, hostname: str) -> Path:
    return store_dir() / site / f"{ip}__{safe_hostname(hostname)}"


def write_snapshot(
    *,
    run_id: str,
    site: str,
    ip: str,
    port: int = 22,
    hostname: str,
    vendor: str,
    netdriver: dict,
    artifacts: dict[str, str],
    status: str,
    error: str | None = None,
) -> Path:
    ts = snapshot_timestamp()
    snap = device_base(site, ip, hostname) / "snapshots" / ts
    snap.mkdir(parents=True, exist_ok=True)
    manifest_artifacts = []
    for name, content in artifacts.items():
        path = snap / f"{name}.txt"
        path.write_text(content or "", encoding="utf-8")
        lines = (content or "").count("\n") + (1 if content else 0)
        manifest_artifacts.append({"name": name, "file": path.name, "lines": lines})
    manifest = {
        "run_id": run_id,
        "site": site,
        "ip": ip,
        "port": port,
        "hostname": hostname,
        "vendor": vendor,
        "netdriver": netdriver,
        "artifacts": manifest_artifacts,
        "status": status,
        "error": error,
        "created_at": ts,
    }
    (snap / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return snap