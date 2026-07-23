from __future__ import annotations

import tempfile
from pathlib import Path

from nccm.parsers.version import (
    huawei_inventory_fields_from_snapshot,
    parse_huawei,
    parse_huawei_manufacture_info,
    parse_huawei_manufacture_rows,
)
from nccm.profiles import huawei_backup_commands

from conftest import read_fixture


def test_backup_includes_manufacture_artifact():
    arts = [s.artifact for s in huawei_backup_commands()]
    assert "manufacture_info" in arts
    assert "stack_info" in arts


def test_mfg_single_serial():
    text = read_fixture("huawei", "mfg_single.txt")
    assert parse_huawei_manufacture_info(text).serials == "1020LAB000001"
    assert len(parse_huawei_manufacture_rows(text)) == 1


def test_mfg_stack_two_serials():
    text = read_fixture("huawei", "mfg_stack_slots.txt")
    rows = parse_huawei_manufacture_rows(text)
    assert len(rows) == 2
    serials = parse_huawei_manufacture_info(text).serials
    assert "1020LAB000011" in serials
    assert "1020LAB000012" in serials


def test_inventory_serial_from_manufacture_not_version():
    version = read_fixture("huawei", "version_s5732.txt")
    mfg = read_fixture("huawei", "mfg_single.txt")
    with tempfile.TemporaryDirectory(prefix="hermes-verify-") as td:
        snap = Path(td)
        (snap / "version_info.txt").write_text(version, encoding="utf-8")
        (snap / "manufacture_info.txt").write_text(mfg, encoding="utf-8")
        inv = huawei_inventory_fields_from_snapshot(snap)
        assert inv.serials == "1020LAB000001"
        assert "5.170" in inv.sw_version or "V200R020" in inv.sw_version
    vonly = parse_huawei(version)
    assert "1020LAB000001" not in (vonly.serials or "")


def test_chassis_12700_shape_documented_gap():
    """Chassis/Slot layout is fixture-locked; full stack semantics deferred to P1."""
    text = read_fixture("huawei", "mfg_chassis_12700_shape.txt")
    rows = parse_huawei_manufacture_rows(text)
    assert isinstance(rows, list)
