#!/usr/bin/env python3
"""Ad-hoc: Huawei stack rows from manufacture-info (like Cisco stack_units)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nccm.parsers.stack import parse_huawei_stack_units

SINGLE = """
Slot  Sub  Serial-number          Manu-date
0     -    1020C0046065           2020-12-09
"""

STACK = """
Slot  Sub  Serial-number          Manu-date
0     -    1020C0046065           2020-12-09
1     -    1020C0046066           2020-12-09
2     -    1020C0046067           2020-12-09
"""


def main() -> int:
    assert parse_huawei_stack_units(SINGLE) == []
    units = parse_huawei_stack_units(STACK, default_sw="8.180", default_model="CE6850")
    assert len(units) == 3
    assert units[0].switch_num == 1 and units[0].role == "Primary"
    assert units[0].serial == "1020C0046065"
    assert units[1].switch_num == 2 and units[1].role == "Member"
    assert units[2].serial == "1020C0046067"
    print("=== ad-hoc huawei-stack verify PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())