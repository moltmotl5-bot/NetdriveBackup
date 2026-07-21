from __future__ import annotations

from nccm.parsers.stack import parse_huawei_stack_units

from conftest import read_fixture


def test_single_slot_not_stack():
    assert parse_huawei_stack_units(read_fixture("huawei", "mfg_single.txt")) == []


def test_multi_slot_stack_units():
    units = parse_huawei_stack_units(
        read_fixture("huawei", "mfg_stack_slots.txt"),
        default_sw="5.170",
        default_model="S5732",
    )
    assert len(units) == 2
    assert units[0].switch_num == 1 and units[0].role == "Primary"
    assert units[0].serial == "1020LAB000011"
    assert units[1].switch_num == 2 and units[1].role == "Member"
    assert units[1].serial == "1020LAB000012"


def test_stack_cli_fixture_present_for_p1():
    text = read_fixture("huawei", "stack_cli.txt")
    assert "Master" in text and "Standby" in text
