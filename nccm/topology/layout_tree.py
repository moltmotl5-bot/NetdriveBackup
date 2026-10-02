from __future__ import annotations

from collections import defaultdict, deque

from nccm.topology.model import TopologyEdge, TopologyNode

CELL_W = 140
CELL_H = 48
H_GAP = 48
V_GAP = 80
MARGIN = 32


def tree_layout(
    nodes: list[TopologyNode],
    edges: list[TopologyEdge],
) -> dict[str, tuple[float, float]]:
    if not nodes:
        return {}

    by_id = {n.node_id: n for n in nodes}
    out_adj: dict[str, list[str]] = defaultdict(list)
    in_deg: dict[str, int] = defaultdict(int)
    for n in nodes:
        in_deg[n.node_id] = 0
    for e in edges:
        if e.target_id in by_id and e.source_id in by_id:
            out_adj[e.source_id].append(e.target_id)
            in_deg[e.target_id] += 1

    roots = [n.node_id for n in nodes if in_deg[n.node_id] == 0]
    if not roots:
        roots = sorted(
            [n.node_id for n in nodes if n.role == "core"],
            key=lambda x: x,
        )
    if not roots:
        roots = [min(by_id.keys(), key=lambda x: (by_id[x].role != "dist", x))]

    depth: dict[str, int] = {}
    q: deque[tuple[str, int]] = deque()
    for r in roots:
        q.append((r, 0))
    while q:
        nid, d = q.popleft()
        if nid in depth and depth[nid] <= d:
            continue
        depth[nid] = d
        for child in sorted(set(out_adj.get(nid, []))):
            q.append((child, d + 1))

    for n in nodes:
        depth.setdefault(n.node_id, 0)

    layers: dict[int, list[str]] = defaultdict(list)
    for nid, d in depth.items():
        layers[d].append(nid)
    for d in layers:
        layers[d].sort(
            key=lambda nid: (
                0 if by_id[nid].role == "core" else 1,
                0 if by_id[nid].node_kind == "aggregate" else 1,
                by_id[nid].label,
            )
        )

    positions: dict[str, tuple[float, float]] = {}
    max_w = 0
    for d in sorted(layers.keys()):
        row = layers[d]
        row_w = len(row) * CELL_W + max(0, len(row) - 1) * H_GAP
        max_w = max(max_w, row_w)
    for d in sorted(layers.keys()):
        row = layers[d]
        row_w = len(row) * CELL_W + max(0, len(row) - 1) * H_GAP
        x0 = MARGIN + (max_w - row_w) / 2
        y = MARGIN + d * (CELL_H + V_GAP)
        for i, nid in enumerate(row):
            x = x0 + i * (CELL_W + H_GAP)
            positions[nid] = (x, y)

    return positions


def canvas_size(positions: dict[str, tuple[float, float]]) -> tuple[float, float]:
    if not positions:
        return (400.0, 240.0)
    max_x = max(x for x, _ in positions.values()) + CELL_W + MARGIN
    max_y = max(y for _, y in positions.values()) + CELL_H + MARGIN
    return (max(max_x, 320.0), max(max_y, 200.0))
