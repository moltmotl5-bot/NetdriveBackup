from __future__ import annotations

from collections import defaultdict, deque

from nccm.topology.model import TopologyEdge, TopologyNode

CELL_W = 140
CELL_H = 48
H_GAP = 48
V_GAP = 80
MARGIN = 32

# Fixed tiers so expanded (non-aggregated) graphs keep uplinks above access/stubs.
_ROLE_LAYER = {
    "core": 0,
    "dist": 1,
    "access": 2,
    "unknown": 2,
    "stub": 3,
}


def _layer_for_node(n: TopologyNode) -> int:
    if n.node_kind == "aggregate":
        return _ROLE_LAYER["access"]
    return _ROLE_LAYER.get(n.role, 2)


def tree_layout(
    nodes: list[TopologyNode],
    edges: list[TopologyEdge],
) -> dict[str, tuple[float, float]]:
    if not nodes:
        return {}

    by_id = {n.node_id: n for n in nodes}
    out_adj: dict[str, list[str]] = defaultdict(list)
    undirected: dict[str, set[str]] = defaultdict(set)
    in_deg: dict[str, int] = defaultdict(int)
    for n in nodes:
        in_deg[n.node_id] = 0
    for e in edges:
        if e.target_id in by_id and e.source_id in by_id:
            out_adj[e.source_id].append(e.target_id)
            undirected[e.source_id].add(e.target_id)
            undirected[e.target_id].add(e.source_id)
            in_deg[e.target_id] += 1

    roots = [n.node_id for n in nodes if n.role == "core"]
    if not roots:
        roots = [n.node_id for n in nodes if in_deg[n.node_id] == 0]
    if not roots:
        roots = sorted([n.node_id for n in nodes if n.role == "dist"], key=lambda x: x)
    if not roots:
        roots = [min(by_id.keys(), key=lambda x: (_layer_for_node(by_id[x]), x))]

    bfs_order: dict[str, int] = {}
    q: deque[str] = deque()
    for r in sorted(roots):
        if r not in bfs_order:
            q.append(r)
            bfs_order[r] = 0
    seq = 0
    while q:
        nid = q.popleft()
        seq += 1
        bfs_order[nid] = seq
        for nb in sorted(undirected.get(nid, ())):
            if nb not in bfs_order:
                bfs_order[nb] = seq
                q.append(nb)

    layers: dict[int, list[str]] = defaultdict(list)
    for n in nodes:
        layers[_layer_for_node(n)].append(n.node_id)
    for d in layers:
        layers[d].sort(
            key=lambda nid: (
                0 if by_id[nid].role == "core" else 1,
                0 if by_id[nid].node_kind == "aggregate" else 1,
                bfs_order.get(nid, 9999),
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
