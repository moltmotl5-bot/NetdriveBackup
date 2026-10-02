from __future__ import annotations

import hashlib
from collections import defaultdict

from nccm.topology.model import TopologyEdge, TopologyNode


def apply_access_aggregation(
    nodes: list[TopologyNode],
    edges: list[TopologyEdge],
    *,
    enabled: bool,
    collapse_threshold: int = 2,
) -> tuple[list[TopologyNode], list[TopologyEdge]]:
    if not enabled:
        return nodes, edges

    by_id = {n.node_id: n for n in nodes}
    out_edges: dict[str, list[TopologyEdge]] = defaultdict(list)
    for e in edges:
        out_edges[e.source_id].append(e)

    dist_ids = [n.node_id for n in nodes if n.role == "dist"]
    if not dist_ids:
        dist_ids = sorted(
            out_degree_candidates(nodes, edges),
            key=lambda nid: -len(out_edges.get(nid, [])),
        )[:3]

    hidden: set[str] = set()
    new_nodes: list[TopologyNode] = []
    new_edges: list[TopologyEdge] = []

    for dist_id in dist_ids:
        dist = by_id.get(dist_id)
        if not dist:
            continue
        buckets: dict[str, list[tuple[TopologyEdge, TopologyNode]]] = defaultdict(list)
        for e in out_edges.get(dist_id, []):
            tgt = by_id.get(e.target_id)
            if not tgt or tgt.node_kind != "physical":
                continue
            if tgt.role not in ("access", "unknown", "stub"):
                continue
            plat = (tgt.platform_model or "__unknown__").strip() or "__unknown__"
            buckets[plat].append((e, tgt))

        for plat, members in buckets.items():
            if len(members) < collapse_threshold:
                continue
            if plat == "__unknown__":
                continue
            group_id = hashlib.sha256(f"{dist_id}|{plat}".encode()).hexdigest()[:16]
            agg_id = f"agg:{group_id}"
            member_keys = [t.node_id for _, t in members]
            for _, t in members:
                hidden.add(t.node_id)
            label_plat = plat if plat != "__unknown__" else "Unknown"
            new_nodes.append(
                TopologyNode(
                    node_id=agg_id,
                    node_kind="aggregate",
                    label=f"[{len(members)}× {label_plat}]",
                    site=dist.site,
                    role="access",
                    group_id=group_id,
                    member_device_keys=member_keys,
                    member_count=len(members),
                    parent_dist_node_id=dist_id,
                    platform_model=plat,
                )
            )
            row_ids: list[str] = []
            for e, _t in members:
                row_ids.extend(e.underlying_row_ids)
            new_edges.append(
                TopologyEdge(
                    edge_id=f"bundle:{group_id}",
                    source_id=dist_id,
                    target_id=agg_id,
                    local_interface="",
                    remote_interface="",
                    protocol="CDP/LLDP",
                    color=members[0][0].color,
                    underlying_row_ids=row_ids,
                )
            )

    kept_nodes = [n for n in nodes if n.node_id not in hidden] + new_nodes
    kept_edges = [
        e for e in edges if e.source_id not in hidden and e.target_id not in hidden
    ]
    kept_edges.extend(new_edges)
    return kept_nodes, kept_edges


def out_degree_candidates(
    nodes: list[TopologyNode], edges: list[TopologyEdge]
) -> list[str]:
    deg: dict[str, int] = defaultdict(int)
    for e in edges:
        deg[e.source_id] += 1
    return [n.node_id for n in nodes if deg.get(n.node_id, 0) >= 2]


def attach_remote_platform(
    nodes: list[TopologyNode],
    edges: list[TopologyEdge],
    neighbor_rows_by_device: dict[str, list[dict]],
) -> None:
    """Set platform_model on physical targets from inbound CDP rows when missing."""
    by_id = {n.node_id: n for n in nodes}
    for src, rows in neighbor_rows_by_device.items():
        for row in rows:
            tgt_key = row.get("remote_device_key")
            plat = (row.get("platform_model") or "").strip()
            if not plat:
                continue
            if tgt_key and tgt_key in by_id and not by_id[tgt_key].platform_model:
                by_id[tgt_key].platform_model = plat
            host_stub = row.get("remote_hostname")
            if host_stub:
                from nccm.topology.model import stub_node_id

                sid = stub_node_id(host_stub)
                if sid in by_id and not by_id[sid].platform_model:
                    by_id[sid].platform_model = plat
