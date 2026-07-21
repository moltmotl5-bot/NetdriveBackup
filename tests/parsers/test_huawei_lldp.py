from __future__ import annotations

import tempfile
from pathlib import Path

from nccm.parsers.cdp_lldp import (
    neighbors_from_backup_snapshot,
    parse_huawei_lldp_neighbor_brief,
    parse_show_lldp_neighbors,
)

# Avoid `import tests.*` — hermes-agent also ships a top-level tests package.
from conftest import read_fixture


def test_huawei_lldp_neighbor_dev_layout():
    text = read_fixture("huawei", "lldp_as_neighbor_dev.txt")
    rows = parse_huawei_lldp_neighbor_brief(text, "local")
    assert len(rows) == 3
    assert rows[0].local_interface == "MultiGE0/0/2"
    assert rows[0].remote_hostname == "LAB-AP-01"
    assert rows[0].remote_port == "MultiGE0/0/0"
    assert rows[2].remote_port == "100GE1/5/0/15"
    assert rows[2].remote_hostname == "LAB-CORE-SW"


def test_huawei_lldp_simunet_exptime_mid():
    text = read_fixture("huawei", "lldp_simunet_exptime_mid.txt")
    rows = parse_huawei_lldp_neighbor_brief(text, "local")
    assert len(rows) == 1
    assert rows[0].remote_hostname == "peer-ce"
    assert rows[0].local_interface == "GE1/0/0"


def test_cisco_lldp_unchanged():
    cisco = """
Device ID           Local Intf     Hold-time  Capability      Port ID
switch2.example.com Gi1/0/1        120        B,R             Gi1/0/2
"""
    assert len(parse_show_lldp_neighbors(cisco, "local")) == 1


def test_neighbors_snapshot_huawei_cdp_na():
    text = read_fixture("huawei", "lldp_as_neighbor_dev.txt")
    with tempfile.TemporaryDirectory(prefix="hermes-verify-") as td:
        snap = Path(td)
        (snap / "lldp.txt").write_text(text, encoding="utf-8")
        rows, cdp_st, lldp_st = neighbors_from_backup_snapshot(
            str(snap), "sw1", "Huawei", {}
        )
        assert cdp_st == "n/a"
        assert lldp_st == "ok"
        assert len(rows) == 3
        assert all(r["protocol"] == "LLDP" for r in rows)
