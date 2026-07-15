#!/usr/bin/env python3
"""Ad-hoc: Huawei device-table Serial = manufacture_info Serial-number only."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nccm.parsers.version import (
    huawei_inventory_fields_from_snapshot,
    parse_huawei,
    parse_huawei_manufacture_info,
)
from nccm.profiles import huawei_backup_commands

MFG = """
Device Manufacture Information:
Slot  Card  Type                         Serial-number         Manu-date
-------------------------------------------------------------------------------
1     -     CE6850-48S4Q-EI              2102351234567890      2020-03-04
2     -     CE6850-48S4Q-EI              2102359876543210      2020-03-04
"""

VERSION = """
VRP (R) software, Version 8.180 (CE6800 V200R005C10SPC607B607)
HUAWEI CE6800 uptime is 1 days
"""


def main() -> int:
    names = [s.artifact for s in huawei_backup_commands()]
    assert "manufacture_info" in names

    mfg_only = parse_huawei_manufacture_info(MFG)
    assert mfg_only.serials == "2102351234567890, 2102359876543210"

    # version_info alone must not drive Serial when manufacture exists
    with tempfile.TemporaryDirectory(prefix="hermes-verify-huawei-serial-") as td:
        snap = Path(td)
        (snap / "version_info.txt").write_text(VERSION, encoding="utf-8")
        (snap / "manufacture_info.txt").write_text(MFG, encoding="utf-8")
        inv = huawei_inventory_fields_from_snapshot(snap)
        assert "2102351234567890" in inv.serials
        assert "8.180" in inv.sw_version
        assert inv.serials != "Unknown"

    # parse_huawei(version) without mfg may still lack serial
    vonly = parse_huawei(VERSION)
    assert vonly.serials == "Unknown" or "210235" not in vonly.serials

    print("=== ad-hoc huawei-manufacture verify PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())