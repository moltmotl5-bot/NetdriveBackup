from __future__ import annotations

import csv
from pathlib import Path

from nccm.config import WLC_VENDOR_ALIASES
from nccm.models import DeviceRow
from nccm.profiles import normalize_vendor


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
        for raw in reader:
            vendor = normalize_vendor(raw.get("Vendor", ""))
            if vendor in WLC_VENDOR_ALIASES or "wlc" in vendor:
                raise ValueError(
                    f"WLC not supported in v3 (row IP={raw.get('IP')}, Vendor={raw.get('Vendor')})"
                )
            port = 22
            if raw.get("Port"):
                try:
                    port = int(str(raw["Port"]).strip())
                except ValueError:
                    port = 22
            hint = ""
            for col in ("Hostname", "hostname", "Name"):
                if col in raw and str(raw.get(col, "")).strip():
                    hint = str(raw[col]).strip()
                    break
            model = str(raw.get("Model", "") or "").strip() or None
            version = str(raw.get("Version", "") or "").strip() or None
            rows.append(
                DeviceRow(
                    site=str(raw["Site"]).strip(),
                    ip=str(raw["IP"]).strip(),
                    vendor=vendor,
                    model=model,
                    version=version,
                    hostname_hint=hint or None,
                    port=port,
                )
            )
    return rows