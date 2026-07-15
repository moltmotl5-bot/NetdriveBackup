#!/usr/bin/env python3
"""Ad-hoc: Huawei manufacture-info → inventory serial_summary."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nccm.parsers.version import parse_huawei
from nccm.profiles import huawei_backup_commands

SAMPLE = """
Device Manufacture Information:
Slot  Card  Type                         Serial-number         Manu-date
-------------------------------------------------------------------------------
1     -     CE6850-48S4Q-EI              2102351234567890      2020-03-04
2     -     CE6850-48S4Q-EI              2102359876543210      2020-03-04
"""

def main() -> int:
    names = [s.artifact for s in huawei_backup_commands()]
    assert "manufacture_info" in names
    cmd = next(s for s in huawei_backup_commands() if s.artifact == "manufacture_info")
    assert "manufacture-info" in cmd.command.lower()

    vf = parse_huawei(SAMPLE)
    assert "2102351234567890" in vf.serials
    assert "CE6850-48S4Q-EI" in vf.models
    print("=== ad-hoc huawei-manufacture verify PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())