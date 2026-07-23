"""Optional tests against local gitignored testdata/ — never required in CI."""
from __future__ import annotations

from pathlib import Path

import pytest

from nccm.parsers.cdp_lldp import parse_huawei_lldp_neighbor_brief
from nccm.parsers.stack import (
    parse_cisco_stack_units,
    parse_fortigate_ha_units,
    parse_huawei_stack_units,
)
from nccm.parsers.version import parse_huawei_manufacture_info, parse_huawei_manufacture_rows

pytestmark = pytest.mark.private


def _need(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"private fixture missing: {path}")
    return path


def test_private_hw_lldp_as(private_testdata: Path):
    p = _need(private_testdata / "HW-LLDP-AS.txt")
    rows = parse_huawei_lldp_neighbor_brief(
        p.read_text(encoding="utf-8", errors="replace"), "x"
    )
    assert len(rows) >= 30
    assert any(r.local_interface.startswith("MultiGE") for r in rows)


def test_private_hw_lldp_12700(private_testdata: Path):
    p = _need(private_testdata / "HW-LLDP-AS_12700.txt")
    rows = parse_huawei_lldp_neighbor_brief(
        p.read_text(encoding="utf-8", errors="replace"), "x"
    )
    assert len(rows) >= 10
    assert any("100GE" in r.local_interface or "40GE" in r.local_interface for r in rows)


def test_private_mfg_single(private_testdata: Path):
    p = _need(private_testdata / "HW-MFG-SINGLE.txt")
    text = p.read_text(encoding="utf-8", errors="replace")
    info = parse_huawei_manufacture_info(text)
    assert info.serials and info.serials != "Unknown"
    assert len(parse_huawei_stack_units("", text)) == 0


def test_private_mfg_stack_slots_alone_not_expand(private_testdata: Path):
    p = _need(private_testdata / "HW-MFG-STACK.txt")
    text = p.read_text(encoding="utf-8", errors="replace")
    assert len(parse_huawei_manufacture_rows(text)) >= 2
    assert parse_huawei_stack_units("", text) == []


def test_private_hw_stack_cli_with_mfg(private_testdata: Path):
    stack_p = _need(private_testdata / "HW-STACK-CLI.txt")
    mfg_p = _need(private_testdata / "HW-MFG-STACK.txt")
    units = parse_huawei_stack_units(
        stack_p.read_text(encoding="utf-8", errors="replace"),
        mfg_p.read_text(encoding="utf-8", errors="replace"),
    )
    assert len(units) >= 2
    assert units[0].role in ("Master", "Primary", "Active")
    assert any(u.serial and u.serial != "Unknown" for u in units)


def test_private_fg_ha(private_testdata: Path):
    p = _need(private_testdata / "FG-HA.txt")
    units = parse_fortigate_ha_units(p.read_text(encoding="utf-8", errors="replace"))
    assert len(units) == 2


def test_private_cs_stack(private_testdata: Path):
    p = _need(private_testdata / "CS-STACK.txt")
    units = parse_cisco_stack_units(p.read_text(encoding="utf-8", errors="replace"))
    assert len(units) >= 2


def test_private_mfg_12700_does_not_crash(private_testdata: Path):
    p = _need(private_testdata / "HW-MFG-STACK_12700.txt")
    text = p.read_text(encoding="utf-8", errors="replace")
    rows = parse_huawei_manufacture_rows(text)
    assert isinstance(rows, list)
