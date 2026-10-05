from __future__ import annotations

from nccm.topology.model import TopologyEdge, TopologyNode
from nccm.topology.render_svg import _abbrev_ifname, render_topology_svg


def test_abbrev_longest_prefix():
    assert _abbrev_ifname("TenGigabitEthernet1/0/1") == "Te1/0/1"
    assert _abbrev_ifname("Ethernet1/10") == "Eth1/10"
    assert "Te" == _abbrev_ifname("TenGigabitEthernet1/0/1")[:2]


def test_svg_split_port_labels_not_on_single_arrow():
    nodes = [
        TopologyNode(
            node_id="a",
            node_kind="physical",
            label="A",
            site="HQ",
            role="dist",
            device_key="a",
        ),
        TopologyNode(
            node_id="b",
            node_kind="physical",
            label="B",
            site="HQ",
            role="core",
            device_key="b",
        ),
    ]
    edges = [
        TopologyEdge(
            edge_id="e1",
            source_id="a",
            target_id="b",
            local_interface="GigabitEthernet1/0/1",
            remote_interface="TenGigabitEthernet1/0/48",
            protocol="CDP",
            color="#6366f1",
        )
    ]
    positions = {"a": (0.0, 120.0), "b": (200.0, 0.0)}
    svg = render_topology_svg(nodes, edges, positions, 400, 240)
    assert svg.count('class="topo-edge-label"') == 2
    assert "Gi1/0/1" in svg
    assert "Te1/0/48" in svg
    assert "↔" not in svg
