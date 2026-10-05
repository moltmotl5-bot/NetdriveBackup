from __future__ import annotations

from nccm.parsers.cdp_lldp import normalize_platform_model, parse_show_cdp_neighbors
from nccm.topology.aggregate import apply_access_aggregation
from nccm.topology.model import TopologyEdge, TopologyNode, build_topology_graph
from conftest import read_fixture


def test_normalize_platform_model():
    assert normalize_platform_model("cisco WS-C2960X-48TS-L") == "C2960X"
    assert normalize_platform_model("") == ""


def test_cdp_detail_includes_platform():
    text = read_fixture("cisco", "cdp_neighbors_detail.txt")
    rows = parse_show_cdp_neighbors(text, "access-sw")
    assert rows[0].platform_raw.startswith("cisco WS-C3750X")
    assert "3750" in normalize_platform_model(rows[0].platform_raw).upper()


def test_access_aggregation_collapses_same_platform():
    dist = TopologyNode(
        node_id="d1",
        node_kind="physical",
        label="DIST-1",
        site="HQ",
        role="dist",
        device_key="d1",
    )
    access = [
        TopologyNode(
            node_id=f"a{i}",
            node_kind="physical",
            label=f"ACC-{i}",
            site="HQ",
            role="access",
            device_key=f"a{i}",
            platform_model="C2960X",
        )
        for i in range(3)
    ]
    nodes = [dist, *access]
    edges = [
        TopologyEdge(
            edge_id=f"e{i}",
            source_id="d1",
            target_id=f"a{i}",
            local_interface=f"Gi1/0/{i}",
            remote_interface="Gi0/1",
            protocol="CDP",
            underlying_row_ids=[f"r{i}"],
        )
        for i in range(3)
    ]
    out_nodes, out_edges = apply_access_aggregation(
        nodes, edges, enabled=True, collapse_threshold=2
    )
    agg = [n for n in out_nodes if n.node_kind == "aggregate"]
    assert len(agg) == 1
    assert agg[0].member_count == 3
    assert len(out_edges) == 1
    assert out_edges[0].target_id == agg[0].node_id


def test_build_topology_graph_stub():
    devices = [{"device_key": "HQ|10.0.0.1|sw1", "site": "HQ", "ip": "10.0.0.1", "hostname": "sw1"}]
    neighbors = {
        "HQ|10.0.0.1|sw1": [
            {
                "local_interface": "Gi1/0/1",
                "protocol": "CDP",
                "remote_hostname": "unknown-neighbor",
                "remote_port": "Gi0/1",
                "cable_type": "gigabit",
                "remote_device_key": None,
            }
        ]
    }
    nodes, edges = build_topology_graph(devices, neighbors)
    assert len(nodes) == 2
    assert len(edges) == 1
    assert any(n.role == "stub" for n in nodes)
