"""Reachability probe via NetDriver Agent TCP /api/v1/probe."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from nccm.models import DeviceRow
from nccm.netdriver.client import NetDriverClient, NetDriverError


@dataclass(frozen=True)
class ProbeResult:
    device: DeviceRow
    ok: bool
    latency_ms: int
    error: str


def probe_device(
    device: DeviceRow,
    *,
    client: NetDriverClient | None = None,
    timeout: float = 3.0,
) -> ProbeResult:
    cli = client or NetDriverClient()
    try:
        data = cli.probe(ip=device.ip, port=device.port or 22, timeout=timeout)
        ok = bool(data.get("ok"))
        return ProbeResult(
            device=device,
            ok=ok,
            latency_ms=int(data.get("latency_ms") or 0),
            error="" if ok else str(data.get("msg") or data.get("code") or "probe failed"),
        )
    except NetDriverError as exc:
        return ProbeResult(device=device, ok=False, latency_ms=0, error=str(exc))


def probe_devices(
    devices: list[DeviceRow],
    *,
    client: NetDriverClient | None = None,
    timeout: float = 3.0,
    max_workers: int = 8,
) -> list[ProbeResult]:
    if not devices:
        return []
    cli = client or NetDriverClient()
    workers = max(1, min(max_workers, len(devices)))
    out: list[ProbeResult | None] = [None] * len(devices)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(probe_device, dev, client=cli, timeout=timeout): idx
            for idx, dev in enumerate(devices)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            out[idx] = fut.result()
    return [r for r in out if r is not None]
