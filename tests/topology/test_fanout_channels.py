from __future__ import annotations

from nccm.topology.model import TopologyEdge
from nccm.topology.render_svg import _fanout_channel_by_edge, _orthogonal_path_coords


def test_fanout_offsets_differ_for_same_source():
    e1 = TopologyEdge(
        edge_id="e1",
        source_id="h2",
        target_id="ds1",
        local_interface="Gi1/0/1",
        remote_interface="Te1/0/1",
        protocol="CDP",
    )
    e2 = TopologyEdge(
        edge_id="e2",
        source_id="h2",
        target_id="ds2",
        local_interface="Gi1/0/2",
        remote_interface="Te1/0/2",
        protocol="CDP",
    )
    positions = {"h2": (200.0, 0.0), "ds1": (80.0, 160.0), "ds2": (320.0, 160.0)}
    ch = _fanout_channel_by_edge([e1, e2], positions)
    assert ch["e1"] != ch["e2"]
    p1 = _orthogonal_path_coords((200, 48), (80, 160), 0, 1, channel_offset=ch["e1"])
    p2 = _orthogonal_path_coords((200, 48), (320, 160), 0, 1, channel_offset=ch["e2"])
    assert p1 != p2
