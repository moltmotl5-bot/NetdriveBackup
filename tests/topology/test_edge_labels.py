from __future__ import annotations

from nccm.topology.model import TopologyEdge, TopologyNode
from nccm.topology.render_svg import _edge_port_label, render_topology_svg


def test_edge_port_label_abbrev():
    assert "Gi1/0/1" in _edge_port_label("GigabitEthernet1/0/1", "TenGigabitEthernet1/0/2")
    assert "↔" in _edge_port_label("GigabitEthernet1/0/1", "TenGigabitEthernet1/0/2")


def test_svg_includes_edge_label_elements():
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
            role="access",
            device_key="b",
        ),
    ]
    edges = [
        TopologyEdge(
            edge_id="e1",
            source_id="a",
            target_id="b",
            local_interface="GigabitEthernet1/0/1",
            remote_interface="GigabitEthernet1/0/48",
            protocol="CDP",
            color="#6366f1",
        )
    ]
    positions = {"a": (0.0, 0.0), "b": (200.0, 120.0)}
    svg = render_topology_svg(nodes, edges, positions, 400, 240)
    assert 'class="topo-edge-label"' in svg
    assert "Gi1/0/1" in svg
    assert '<svg xmlns' in svg and 'class="topo-labels-visible"' not in svg.split(">", 1)[0]
