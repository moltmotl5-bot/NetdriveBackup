"""Build PuTTY-compatible logs from NCCM snapshot artifacts for SwitchDraw / SwitchMap."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from nccm.parsers.interface_map import strip_nccm_header
from nccm.storage.store_paths import resolve_snapshot_dir, resolve_snapshot_file

# Order matches SwitchDraw README / PuTTY capture sequence.
_LOG_SECTIONS: tuple[tuple[str, str], ...] = (
    ("config", "show running-config"),
    ("interfaces", "show interfaces status"),
    ("interfaces_description", "show interfaces description"),
    ("ip_interface_brief", "show ip interface brief"),
    ("vlan_brief", "show vlan brief"),
    ("cdp_neighbors", "show cdp neighbors detail"),
    ("lldp_neighbors", "show lldp neighbors detail"),
)


@dataclass(frozen=True)
class SwitchdrawLogResult:
    log_text: str
    snapshot_ts: str
    hostname: str
    missing_artifacts: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _hostname_from_config(config_text: str, fallback: str) -> str:
    m = re.search(r"^hostname\s+(\S+)", config_text or "", re.MULTILINE | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return (fallback or "Switch").strip() or "Switch"


def _read_artifact(snapshot_dir: Path, artifact: str) -> str | None:
    path = resolve_snapshot_file(snapshot_dir, f"{artifact}.txt")
    if not path.is_file():
        return None
    return strip_nccm_header(path.read_text(encoding="utf-8", errors="replace"))


def build_switchdraw_log(
    snapshot_dir: str | Path,
    *,
    prompt_hostname: str = "",
) -> SwitchdrawLogResult:
    """Concatenate snapshot artifacts into a SwitchDraw-compatible session log."""
    snap = resolve_snapshot_dir(snapshot_dir)
    ts = snap.name
    missing: list[str] = []
    warnings: list[str] = []
    chunks: list[str] = []

    config_body = _read_artifact(snap, "config")
    hostname = _hostname_from_config(config_body or "", prompt_hostname)

    if config_body is None:
        missing.append("config")
        warnings.append("缺少 config.txt，SwitchDraw 無法解析 hostname／介面設定。")

    chunks.append(f"{hostname}#terminal length 0")
    chunks.append(f"{hostname}#terminal width 0")

    for artifact, command in _LOG_SECTIONS:
        body = _read_artifact(snap, artifact)
        if body is None:
            missing.append(artifact)
            if artifact == "interfaces":
                warnings.append(
                    "缺少 interfaces.txt（show interfaces status），"
                    "前面板連線狀態可能無法顯示；請重新備份。"
                )
            elif artifact in ("vlan_brief", "interfaces_description", "ip_interface_brief"):
                warnings.append(f"缺少 {artifact}.txt，部分欄位可能不完整。")
            continue
        if not body.strip():
            warnings.append(f"{artifact}.txt 為空。")
        chunks.append(f"{hostname}#{command}")
        chunks.append(body.rstrip())

    log_text = "\n".join(chunks).rstrip() + "\n"
    return SwitchdrawLogResult(
        log_text=log_text,
        snapshot_ts=ts,
        hostname=hostname,
        missing_artifacts=tuple(missing),
        warnings=tuple(warnings),
    )


def resolve_snapshot_path_for_device(
    store_path: str | Path,
    snapshot_ts: str = "",
) -> Path | None:
    """Return newest or requested snapshot directory under a device store."""
    from nccm.parsers.cdp_lldp import list_device_backup_versions

    store = Path(store_path)
    versions = list_device_backup_versions(str(store), limit=50)
    if not versions:
        return None
    ts = snapshot_ts if snapshot_ts in versions else versions[0]
    snap = store / "snapshots" / ts
    if not snap.is_dir():
        return None
    return resolve_snapshot_dir(snap)
