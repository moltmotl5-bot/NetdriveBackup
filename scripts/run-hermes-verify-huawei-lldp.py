#!/usr/bin/env python3
"""Ad-hoc: Huawei LLDP brief + Cisco LLDP unchanged."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nccm.parsers.cdp_lldp import (
    neighbors_from_backup_snapshot,
    parse_huawei_lldp_neighbor_brief,
    parse_show_lldp_neighbors,
)

HUAWEI = """
Local Interface         Exptime(s) Neighbor Interface      Neighbor Device
GE1/0/0                 120        GE1/0/1                 peer-ce
"""

CISCO = """
Device ID           Local Intf     Hold-time  Capability      Port ID
switch2.example.com Gi1/0/1        120        B,R             Gi1/0/2
"""


def main() -> int:
    recs = parse_huawei_lldp_neighbor_brief(HUAWEI, "local")
    assert len(recs) == 1, recs
    assert recs[0].local_interface == "GE1/0/0"
    assert recs[0].remote_port == "GE1/0/1"
    assert recs[0].remote_hostname == "peer-ce"

    cisco = parse_show_lldp_neighbors(CISCO, "local")
    assert len(cisco) == 1
    assert "Gi1/0/1" in cisco[0].local_interface or cisco[0].local_interface.startswith("Gi")

    with tempfile.TemporaryDirectory(prefix="hermes-verify-") as td:
        snap = Path(td)
        (snap / "lldp.txt").write_text(HUAWEI, encoding="utf-8")
        rows, cdp_st, lldp_st = neighbors_from_backup_snapshot(
            str(snap), "sw1", "Huawei", {}
        )
        assert cdp_st == "missing"
        assert lldp_st == "ok"
        assert len(rows) == 1 and rows[0]["protocol"] == "LLDP"

    print("=== ad-hoc huawei-lldp verify PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())