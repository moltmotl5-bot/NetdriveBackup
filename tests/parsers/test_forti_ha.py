from __future__ import annotations

from nccm.parsers.stack import parse_fortigate_ha_units

from conftest import read_fixture


def test_fortigate_ha_two_units():
    units = parse_fortigate_ha_units(read_fixture("fortinet", "ha_status.txt"))
    assert len(units) == 2
    by_role = {u.role: u for u in units}
    assert "Primary" in by_role and "Secondary" in by_role
    assert by_role["Primary"].hostname == "LAB-FG-PRI"
    assert by_role["Primary"].serial == "FG4H0LAB00000001"
    assert by_role["Secondary"].hostname == "LAB-FG-SEC"
    assert by_role["Secondary"].serial == "FG4H0LAB00000002"
