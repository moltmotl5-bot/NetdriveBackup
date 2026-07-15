#!/usr/bin/env python3
"""Ad-hoc: Huawei LLDP brief (VRP Local Intf / Neighbor Dev layout)."""
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

REAL = """
Local Intf       Neighbor Dev             Neighbor Intf             Exptime(s)
MultiGE0/0/2     A2-01Z06-01-W574         MultiGE0/0/0              117
40GE0/0/1        A2-Guest-Core-SW         100GE1/5/0/15             107
"""

SIMUNET = """
Local Interface         Exptime(s) Neighbor Interface      Neighbor Device
GE1/0/0                 120        GE1/0/1                 peer-ce
"""

CISCO = """
Device ID           Local Intf     Hold-time  Capability      Port ID
switch2.example.com Gi1/0/1        120        B,R             Gi1/0/2
"""


def main() -> int:
    real = parse_huawei_lldp_neighbor_brief(REAL, "local")
    assert len(real) == 2
    assert real[0].remote_hostname == "A2-01Z06-01-W574"
    assert real[1].remote_port == "100GE1/5/0/15"

    sim = parse_huawei_lldp_neighbor_brief(SIMUNET, "local")
    assert len(sim) == 1 and sim[0].remote_hostname == "peer-ce"

    cisco = parse_show_lldp_neighbors(CISCO, "local")
    assert len(cisco) == 1

    with tempfile.TemporaryDirectory(prefix="hermes-verify-") as td:
        snap = Path(td)
        (snap / "lldp.txt").write_text(REAL, encoding="utf-8")
        rows, cdp_st, lldp_st = neighbors_from_backup_snapshot(
            str(snap), "sw1", "Huawei", {}
        )
        assert cdp_st == "n/a"
        assert lldp_st == "ok"
        assert len(rows) == 2
        assert all(r["protocol"] == "LLDP" for r in rows)

    print("=== ad-hoc huawei-lldp verify PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())