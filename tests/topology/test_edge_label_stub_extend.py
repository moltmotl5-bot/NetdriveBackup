from __future__ import annotations

from nccm.topology.render_svg import (
    _extend_coords_for_labels,
    _label_plan,
    _segments_from_coords,
)


def test_extend_vertical_when_two_ports_on_same_stub():
    coords = [(100.0, 200.0), (100.0, 185.0)]
    segs = _segments_from_coords(coords)
    counts, _ = _label_plan(segs, "Gi1/0/1", "Te1/0/2")
    assert counts.get(0) == 2
    extended = _extend_coords_for_labels(coords, segs, dict(counts))
    segs2 = _segments_from_coords(extended)
    assert segs2[0].length >= 2 * 15 + 10 - 0.5
