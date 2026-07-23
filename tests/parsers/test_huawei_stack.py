from __future__ import annotations

from nccm.parsers.stack import (
    parse_huawei_display_stack,
    parse_huawei_stack_units,
)
from nccm.profiles import huawei_backup_commands

from conftest import read_fixture


def test_backup_includes_stack_info():
    arts = [s.artifact for s in huawei_backup_commands()]
    assert "stack_info" in arts
    assert "manufacture_info" in arts
    cmd = next(s.command for s in huawei_backup_commands() if s.artifact == "stack_info")
    assert cmd == "display stack"


def test_single_mfg_not_stack():
    assert parse_huawei_stack_units("", read_fixture("huawei", "mfg_single.txt")) == []
    assert parse_huawei_stack_units(read_fixture("huawei", "mfg_single.txt")) == []


def test_multi_mfg_alone_not_stack():
    """≥2 manufacture slots without display stack must NOT expand (P1.1)."""
    mfg = read_fixture("huawei", "mfg_stack_slots.txt")
    assert parse_huawei_stack_units("", mfg) == []
    assert parse_huawei_stack_units(mfg) == []


def test_display_stack_two_members():
    stack = read_fixture("huawei", "stack_cli.txt")
    units = parse_huawei_display_stack(stack, default_sw="5.170")
    assert len(units) == 2
    assert units[0].switch_num == 1 and units[0].role == "Master"
    assert units[0].model == "S5732-H48UM2CC"
    assert units[1].switch_num == 2 and units[1].role == "Standby"
    assert units[1].model == "S5732-H24UM2CC"
    assert units[0].serial == "Unknown"  # not yet enriched


def test_stack_plus_manufacture_serials():
    stack = read_fixture("huawei", "stack_cli.txt")
    mfg = read_fixture("huawei", "mfg_stack_slots.txt")
    units = parse_huawei_stack_units(stack, mfg, default_sw="5.170")
    assert len(units) == 2
    assert units[0].role == "Master"
    assert units[0].serial == "1020LAB000011"
    assert units[1].role == "Standby"
    assert units[1].serial == "1020LAB000012"
    assert "S5732" in units[0].model


def test_chassis_mfg_alone_not_stack():
    mfg = read_fixture("huawei", "mfg_chassis_12700_shape.txt")
    assert parse_huawei_stack_units("", mfg) == []
