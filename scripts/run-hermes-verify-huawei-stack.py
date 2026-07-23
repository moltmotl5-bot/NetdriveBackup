#!/usr/bin/env python3
"""Ad-hoc: Huawei stack from display stack CLI; manufacture only enriches serials."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nccm.parsers.stack import parse_huawei_display_stack, parse_huawei_stack_units
from nccm.profiles import huawei_backup_commands

SINGLE_MFG = """
Slot  Sub  Serial-number          Manu-date
0     -    1020C0046065           2020-12-09
"""

STACK_MFG = """
Slot  Sub  Serial-number          Manu-date
0     -    1020C0046065           2020-12-09
1     -    1020C0046066           2020-12-09
"""

STACK_CLI = """
Stack mode: Service-port
Stack topology type: Ring
Slot      Role        MAC Address      Priority   Device Type
-------------------------------------------------------------
0         Master      aaaa-bbbb-cccc   200        S5732-H48UM2CC
1         Standby     dddd-eeee-ffff   150        S5732-H24UM2CC
"""


def main() -> int:
    arts = [s.artifact for s in huawei_backup_commands()]
    assert "stack_info" in arts
    assert next(s.command for s in huawei_backup_commands() if s.artifact == "stack_info") == (
        "display stack"
    )

    assert parse_huawei_stack_units("", SINGLE_MFG) == []
    assert parse_huawei_stack_units("", STACK_MFG) == []
    assert parse_huawei_stack_units(STACK_MFG) == []  # mfg alone is not stack

    bare = parse_huawei_display_stack(STACK_CLI)
    assert len(bare) == 2
    assert bare[0].role == "Master" and bare[1].role == "Standby"

    units = parse_huawei_stack_units(STACK_CLI, STACK_MFG, default_sw="5.170")
    assert len(units) == 2
    assert units[0].switch_num == 1 and units[0].serial == "1020C0046065"
    assert units[1].switch_num == 2 and units[1].serial == "1020C0046066"
    assert units[0].model == "S5732-H48UM2CC"

    # Private lab sample if present (never required)
    private = ROOT / "testdata" / "HW-STACK-CLI.txt"
    private_mfg = ROOT / "testdata" / "HW-MFG-STACK.txt"
    if private.is_file() and private_mfg.is_file():
        u = parse_huawei_stack_units(
            private.read_text(encoding="utf-8", errors="replace"),
            private_mfg.read_text(encoding="utf-8", errors="replace"),
        )
        assert len(u) >= 2, f"lab stack expected ≥2, got {len(u)}"
        assert any(x.serial and x.serial != "Unknown" for x in u)

    print("=== ad-hoc huawei-stack verify PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
