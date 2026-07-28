from __future__ import annotations

import csv
from pathlib import Path

from nccm.config import WLC_VENDOR_ALIASES
from nccm.models import DeviceRow
from nccm.profiles import normalize_vendor
from nccm.registry.csv_validation import (
    validate_hostname_hint,
    validate_ip,
    validate_port,
    validate_site,
)


def load_devices_csv(path: Path) -> list[DeviceRow]:
    rows: list[DeviceRow] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV has no header")
        fields = {c.strip() for c in reader.fieldnames}
        for req in ("Site", "IP", "Vendor"):
            if req not in fields:
                raise ValueError(f"CSV missing column: {req}")
        for line_no, raw in enumerate(reader, start=2):
            row_hint = f" (CSV line {line_no}, IP={raw.get('IP')!r})"
            vendor = normalize_vendor(raw.get("Vendor", ""))
            if vendor in WLC_VENDOR_ALIASES or "wlc" in vendor:
                raise ValueError(
                    f"WLC not supported in v3{row_hint}, Vendor={raw.get('Vendor')}"
                )
            site = validate_site(str(raw["Site"]), row_hint=row_hint)
            ip = validate_ip(str(raw["IP"]), row_hint=row_hint)
            port = validate_port(raw.get("Port"), row_hint=row_hint)
            hint = ""
            for col in ("Hostname", "hostname", "Name"):
                if col in raw and str(raw.get(col, "")).strip():
                    hint = str(raw[col]).strip()
                    break
            hostname_hint = validate_hostname_hint(hint, row_hint=row_hint)
            model = str(raw.get("Model", "") or "").strip() or None
            version = str(raw.get("Version", "") or "").strip() or None
            rows.append(
                DeviceRow(
                    site=site,
                    ip=ip,
                    vendor=vendor,
                    model=model,
                    version=version,
                    hostname_hint=hostname_hint,
                    port=port,
                )
            )
    return rows


def load_devices_csv_text(csv_text: str) -> list[DeviceRow]:
    import tempfile

    body = (csv_text or "").strip()
    if not body:
        raise ValueError("empty csv")
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
        tmp.write(body)
        path = Path(tmp.name)
    try:
        return load_devices_csv(path)
    finally:
        path.unlink(missing_ok=True)


def devices_to_csv(devices: list[DeviceRow]) -> str:
    if not devices:
        raise ValueError("no devices")
    lines = ["Site,IP,Vendor,Port"]
    for d in devices:
        port = d.port or 22
        lines.append(f"{d.site},{d.ip},{d.vendor},{port}")
    return "\n".join(lines) + "\n"
