from __future__ import annotations

import uuid
from typing import Callable

from nccm.discovery.auto import classify_from_version_output
from nccm.models import BackupResult, DeviceRow, NetDriverProfile
from nccm.netdriver.client import NetDriverClient, NetDriverError
from nccm.profiles import (
    backup_commands,
    default_probe_profile,
    hostname_from_output,
    normalize_vendor,
    profile_from_csv,
    version_command,
)
from nccm.storage.writer import write_snapshot


LogFn = Callable[[str], None]

_VERSION_FALLBACK: dict[str, str] = {
    "fortinet": "show full-configuration",
    "huawei": "display current-configuration",
}


def _fetch_version_text(
    client: NetDriverClient,
    row: DeviceRow,
    username: str,
    password: str,
    enable_password: str,
    profile: NetDriverProfile,
    log: LogFn,
) -> str:
    primary = version_command(row.vendor)
    try:
        return client.cmd(
            ip=row.ip,
            port=row.port,
            username=username,
            password=password,
            profile=profile,
            command=primary,
            enable_password=enable_password,
            timeout=120,
        )
    except NetDriverError as exc:
        fb = _VERSION_FALLBACK.get(normalize_vendor(row.vendor))
        if not fb:
            raise
        log(f"{row.ip}: {primary} failed ({exc}); fallback {fb}")
        text = client.cmd(
            ip=row.ip,
            port=row.port,
            username=username,
            password=password,
            profile=profile,
            command=fb,
            enable_password=enable_password,
            timeout=300,
        )
        return "\n".join(text.splitlines()[:80])


def _resolve_profile(
    client: NetDriverClient,
    row: DeviceRow,
    username: str,
    password: str,
    enable_password: str,
    log: LogFn,
) -> tuple[NetDriverProfile, str, str]:
    """Return (profile, discovery_mode, version_text)."""
    explicit = profile_from_csv(row.vendor, row.model, row.version)
    if explicit:
        log(f"{row.ip}: using CSV profile {explicit.vendor}/{explicit.model}/{explicit.version}")
        probe = explicit
        discovery = "csv"
    else:
        probe = default_probe_profile(row.vendor, row.port)
        discovery = "auto"
        log(f"{row.ip}: probing with {probe.vendor}/{probe.model}/{probe.version}")

    client.connect(
        ip=row.ip,
        port=row.port,
        username=username,
        password=password,
        profile=probe,
        enable_password=enable_password,
    )
    vcmd = version_command(row.vendor)
    version_text = _fetch_version_text(
        client, row, username, password, enable_password, probe, log
    )

    final = probe
    if discovery == "auto":
        classified = classify_from_version_output(row.vendor, version_text)
        if classified and (classified.model, classified.version) != (probe.model, probe.version):
            log(
                f"{row.ip}: auto classified → {classified.model}/{classified.version}, reconnecting"
            )
            client.disconnect(
                ip=row.ip,
                port=row.port,
                username=username,
                password=password,
                profile=probe,
            )
            client.connect(
                ip=row.ip,
                port=row.port,
                username=username,
                password=password,
                profile=classified,
                enable_password=enable_password,
            )
            final = classified
        elif classified:
            final = classified

    return final, discovery, version_text


def backup_device(
    client: NetDriverClient,
    row: DeviceRow,
    *,
    run_id: str,
    username: str,
    password: str,
    enable_password: str = "",
    log: LogFn | None = None,
) -> BackupResult:
    _log = log or (lambda _m: None)
    profile: NetDriverProfile | None = None
    hostname = row.hostname_hint or "unknown"
    discovery = ""
    version_text = ""
    try:
        profile, discovery, version_text = _resolve_profile(
            client, row, username, password, enable_password, _log
        )
        hostname = hostname_from_output(row.vendor, version_text)
        if row.hostname_hint and hostname == "unknown":
            hostname = row.hostname_hint

        artifacts: dict[str, str] = {}
        for spec in backup_commands(row.vendor, profile.model):
            if (
                spec.artifact == "version_info"
                and version_text
                and normalize_vendor(row.vendor) in ("fortinet", "huawei")
            ):
                artifacts[spec.artifact] = version_text
                _log(f"{row.ip}: {spec.command} (reused probe output)")
                continue
            _log(f"{row.ip}: {spec.command}")
            try:
                out = client.cmd(
                    ip=row.ip,
                    port=row.port,
                    username=username,
                    password=password,
                    profile=profile,
                    command=spec.command,
                    mode=spec.mode,
                    enable_password=enable_password,
                    timeout=spec.timeout,
                )
            except NetDriverError as exc:
                if spec.artifact in ("interfaces", "cdp", "lldp"):
                    _log(f"{row.ip}: skip {spec.artifact} ({exc})")
                    artifacts[spec.artifact] = ""
                    continue
                raise
            artifacts[spec.artifact] = out

        # Prefer hostname from running-config (authoritative; "hostname XXX" is usually not in "show version")
        config_text = artifacts.get("config", "")
        if config_text:
            cfg_host = hostname_from_output(row.vendor, config_text)
            if cfg_host and cfg_host != "unknown":
                hostname = cfg_host
        if row.hostname_hint and hostname == "unknown":
            hostname = row.hostname_hint

        snap = write_snapshot(
            run_id=run_id,
            site=row.site,
            ip=row.ip,
            port=row.port,
            hostname=hostname,
            vendor=normalize_vendor(row.vendor),
            netdriver={
                "vendor": profile.vendor,
                "model": profile.model,
                "version": profile.version,
                "discovery": discovery,
            },
            artifacts=artifacts,
            status="ok",
        )
        client.disconnect(
            ip=row.ip,
            port=row.port,
            username=username,
            password=password,
            profile=profile,
        )
        manifest_path = snap / "manifest.json"
        import json

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        from nccm.storage.index_db import index_manifest

        index_manifest(manifest, snap)
        return BackupResult(
            site=row.site,
            ip=row.ip,
            hostname=hostname,
            status="ok",
            snapshot_dir=str(snap),
            manifest=manifest,
        )
    except (NetDriverError, OSError, ValueError) as exc:
        if profile:
            try:
                client.disconnect(
                    ip=row.ip,
                    port=row.port,
                    username=username,
                    password=password,
                    profile=profile,
                )
            except Exception:
                pass
        failed_host = hostname
        return BackupResult(
            site=row.site,
            ip=row.ip,
            hostname=failed_host,
            status="failed",
            error=str(exc),
        )


def run_backup_job(
    devices: list[DeviceRow],
    *,
    username: str,
    password: str,
    enable_password: str = "",
    agent_url: str | None = None,
    log: LogFn | None = None,
) -> tuple[str, list[BackupResult]]:
    run_id = uuid.uuid4().hex[:12]
    client = NetDriverClient(base_url=agent_url) if agent_url else NetDriverClient()
    if not client.health():
        raise NetDriverError(
            "NetDriver Agent not reachable; start agent and set NCCM_NETDRIVER_URL"
        )
    results: list[BackupResult] = []
    for row in devices:
        if log:
            log(f"--- {row.site} {row.ip} ({row.vendor}) ---")
        results.append(
            backup_device(
                client,
                row,
                run_id=run_id,
                username=username,
                password=password,
                enable_password=enable_password,
                log=log,
            )
        )
    return run_id, results