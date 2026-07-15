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

# Lab / SimuNet (Slot Card Type …)
MFG_CE = """
Device Manufacture Information:
Slot  Card  Type                         Serial-number         Manu-date
-------------------------------------------------------------------------------
1     -     CE6850-48S4Q-EI              2102351234567890      2020-03-04
"""

# Real fixed switch (Slot Sub Serial-number) — 12-char serial
MFG_REAL = """
===== start exec cmd: [display device manufacture-info] =====
<A2-0MZ02-U29-G-AS1>display device manufacture-info
Slot  Sub  Serial-number          Manu-date
- - - - - - - - - - - - - - - - - - - - - -
0     -    1020C0046065           2020-12-09
<A2-0MZ02-U29-G-AS1>
===== end exec cmd =====
"""

VERSION = """
VRP (R) software, Version 8.180 (CE6800 V200R005C10SPC607B607)
HUAWEI CE6800 uptime is 1 days
"""


def main() -> int:
    assert "manufacture_info" in [s.artifact for s in huawei_backup_commands()]

    real = parse_huawei_manufacture_info(MFG_REAL)
    assert real.serials == "1020C0046065", real.serials

    ce = parse_huawei_manufacture_info(MFG_CE)
    assert "2102351234567890" in ce.serials

    with tempfile.TemporaryDirectory(prefix="hermes-verify-huawei-serial-") as td:
        snap = Path(td)
        (snap / "version_info.txt").write_text(VERSION, encoding="utf-8")
        (snap / "manufacture_info.txt").write_text(MFG_REAL, encoding="utf-8")
        inv = huawei_inventory_fields_from_snapshot(snap)
        assert inv.serials == "1020C0046065"
        assert "8.180" in inv.sw_version

    vonly = parse_huawei(VERSION)
    assert "1020C0046065" not in vonly.serials

    print("=== ad-hoc huawei-manufacture verify PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())