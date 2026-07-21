from __future__ import annotations

from nccm.parsers.stack import parse_cisco_stack_units

from conftest import read_fixture


def test_cisco_stack_two_members():
    text = read_fixture("cisco", "stack_show_switch.txt")
    units = parse_cisco_stack_units(text)
    assert len(units) >= 2
    roles = {u.role.lower() for u in units}
    assert roles & {"master", "active", "member", "standby"}
    serials = {u.serial for u in units if u.serial and u.serial != "Unknown"}
    assert serials
