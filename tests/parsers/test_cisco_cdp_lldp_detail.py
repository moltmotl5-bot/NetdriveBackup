from __future__ import annotations

from nccm.parsers.cdp_lldp import (
    neighbors_from_backup_snapshot,
    parse_show_cdp_neighbors,
    parse_show_lldp_neighbors,
)
from conftest import read_fixture


def test_cdp_detail_parser():
    text = read_fixture("cisco", "cdp_neighbors_detail.txt")
    rows = parse_show_cdp_neighbors(text, "access-sw")
    assert len(rows) == 2
    assert rows[0].local_interface == "GigabitEthernet1/0/48"
    assert rows[0].remote_hostname == "DIST-SW01"
    assert rows[0].remote_port == "GigabitEthernet1/0/1"
    assert rows[0].platform_raw.startswith("cisco WS-C3750X")
    assert rows[1].remote_port == "TenGigabitEthernet1/0/1"


def test_cdp_brief_still_parses():
    text = read_fixture("cisco", "cdp_neighbors_brief.txt")
    rows = parse_show_cdp_neighbors(text, "access-sw")
    assert len(rows) == 1
    assert rows[0].remote_hostname == "DIST-SW01"


def test_lldp_detail_parser():
    text = read_fixture("cisco", "lldp_neighbors_detail.txt")
    rows = parse_show_lldp_neighbors(text, "access-sw")
    assert len(rows) == 2
    assert rows[0].local_interface == "GigabitEthernet1/0/1"
    assert rows[0].remote_hostname == "dist-sw01"
    assert rows[0].remote_port == "GigabitEthernet1/0/24"


def test_neighbors_snapshot_reads_cdp_neighbors_artifact():
    text = read_fixture("cisco", "cdp_neighbors_detail.txt")
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp)
        (snap / "cdp_neighbors.txt").write_text(text, encoding="utf-8")
        rows, cdp_st, lldp_st = neighbors_from_backup_snapshot(
            str(snap), "access-sw", "Cisco", {}
        )
        assert cdp_st == "ok"
        assert lldp_st in ("missing", "skipped")
        assert len(rows) == 2
