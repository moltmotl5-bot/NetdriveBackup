from __future__ import annotations

from nccm.topology.model import TopologyEdge
from nccm.topology.render_svg import (
    _extend_coords_for_labels,
    _label_plan,
    _label_stack_extent,
    _labels_from_plan,
    _segments_from_coords,
    _spread_segment_labels,
)


def test_extend_vertical_when_two_ports_on_same_stub():
    coords = [(100.0, 200.0), (100.0, 185.0)]
    segs = _segments_from_coords(coords)
    counts, placements, column_pair, column_labels = _label_plan(
        segs, "Gi1/0/1", "Te1/0/2"
    )
    assert counts.get(0) == 2
    assert not column_pair
    extended = _extend_coords_for_labels(
        coords,
        segs,
        dict(counts),
        column_pair=column_pair,
        column_label_count=column_labels,
    )
    segs2 = _segments_from_coords(extended)
    assert segs2[0].length >= 58 - 0.5


def test_two_port_labels_on_short_vertical_do_not_overlap_after_spread():
    coords = [(100.0, 50.0), (100.0, 70.0)]
    segs = _segments_from_coords(coords)
    counts, placements, column_pair, column_labels = _label_plan(
        segs, "Te1/0/1", "Eth1/17"
    )
    extended = _extend_coords_for_labels(
        coords,
        segs,
        dict(counts),
        column_pair=column_pair,
        column_label_count=column_labels,
    )
    edge = TopologyEdge("e", "a", "b", "", "", "CDP", "#6366f1")
    labels = _labels_from_plan(edge, extended, placements)
    _spread_segment_labels(labels)
    assert len(labels) == 2
    gap = labels[1].y - labels[0].y
    need = (_label_stack_extent(labels[0]) + _label_stack_extent(labels[1])) / 2
    assert gap >= need
