from __future__ import annotations

from nccm.topology.layout_tree import tree_layout
from nccm.topology.model import (
    TopologyEdge,
    TopologyNode,
    build_topology_graph,
    merge_stub_with_inventory_nodes,
)


def test_role_layers_keep_dist_above_access_when_only_uplinks():
    core = TopologyNode(
        node_id="c1",
        node_kind="physical",
        label="H2-CORE",
        site="HQ",
        role="core",
        device_key="c1",
        hostname="H2-CORE",
    )
    dist = TopologyNode(
        node_id="d1",
        node_kind="physical",
        label="DS-SW-L1D-1A",
        site="HQ",
        role="dist",
        device_key="d1",
        hostname="DS-SW-L1D-1A",
    )
    access = TopologyNode(
        node_id="a1",
        node_kind="physical",
        label="ACC-1",
        site="HQ",
        role="access",
        device_key="a1",
        hostname="ACC-1",
    )
    nodes = [core, dist, access]
    edges = [
        TopologyEdge(
            edge_id="e1",
            source_id="c1",
            target_id="d1",
            local_interface="Te1/0/1",
            remote_interface="Te1/0/48",
            protocol="CDP",
        ),
        TopologyEdge(
            edge_id="e2",
            source_id="a1",
            target_id="d1",
            local_interface="Gi0/1",
            remote_interface="Gi1/0/10",
            protocol="CDP",
        ),
    ]
    pos = tree_layout(nodes, edges)
    assert pos["c1"][1] < pos["d1"][1] < pos["a1"][1]


def test_merge_stub_redirects_edge_to_inventory_device():
    devices = [
        {
            "device_key": "HQ|10.0.0.10|dist1",
            "site": "HQ",
            "ip": "10.0.0.10",
            "hostname": "dist1",
        },
        {
            "device_key": "HQ|10.0.0.20|acc-sw",
            "site": "HQ",
            "ip": "10.0.0.20",
            "hostname": "acc-sw",
        },
    ]
    neighbors = {
        "HQ|10.0.0.10|dist1": [
            {
                "local_interface": "Gi1/0/1",
                "protocol": "CDP",
                "remote_hostname": "acc-sw",
                "remote_port": "Gi0/1",
                "cable_type": "gigabit",
                "remote_device_key": None,
            }
        ]
    }
    nodes, edges = build_topology_graph(devices, neighbors)
    assert any(n.node_id.startswith("hn:") for n in nodes)
    merged_nodes, merged_edges = merge_stub_with_inventory_nodes(nodes, edges)
    assert not any(n.node_id.startswith("hn:") for n in merged_nodes)
    assert merged_edges[0].target_id == "HQ|10.0.0.20|acc-sw"
