from __future__ import annotations

from nccm.parsers.stack import (
    member_display_hostname,
    normalize_stack_display_role,
    parse_cisco_stack_units,
    parse_huawei_stack_units,
)

from conftest import read_fixture


def test_cisco_stack_two_members():
    text = read_fixture("cisco", "stack_show_switch.txt")
    units = parse_cisco_stack_units(text)
    assert len(units) >= 2
    roles = {u.role.lower() for u in units}
    assert roles & {"master", "active", "member", "standby"}
    serials = {u.serial for u in units if u.serial and u.serial != "Unknown"}
    assert serials


def test_cisco_stack_display_aligns_with_huawei():
    """Inventory Role column: stack uses Master/Standby (not Forti Primary/Secondary)."""
    cisco = parse_cisco_stack_units(read_fixture("cisco", "stack_show_switch.txt"))
    huawei = parse_huawei_stack_units(
        read_fixture("huawei", "stack_cli.txt"),
        read_fixture("huawei", "mfg_stack_slots.txt"),
        default_sw="5.170",
    )
    assert len(cisco) >= 2 and len(huawei) >= 2

    c_roles = [normalize_stack_display_role(u.role, vendor="cisco") for u in cisco]
    h_roles = [normalize_stack_display_role(u.role, vendor="huawei") for u in huawei]
    assert c_roles[0] == h_roles[0] == "Master"
    assert "Primary" not in c_roles and "Primary" not in h_roles
    assert set(c_roles) <= {"Master", "Standby", "Member"}
    assert set(h_roles) <= {"Master", "Standby", "Member"}

    c_host = member_display_hostname("LAB-SW1", cisco[0], vendor="cisco")
    h_host = member_display_hostname("HW-CORE", huawei[0], vendor="huawei")
    assert c_host.endswith(f" · SW{cisco[0].switch_num}")
    assert h_host.endswith(f" · SW{huawei[0].switch_num}")

    assert normalize_stack_display_role("Active", vendor="cisco") == "Master"
    assert normalize_stack_display_role("Master", vendor="huawei") == "Master"
    assert normalize_stack_display_role("Primary", vendor="fortinet") == "Primary"
    assert normalize_stack_display_role("Secondary", vendor="fortinet") == "Secondary"
