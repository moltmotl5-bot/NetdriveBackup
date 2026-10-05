from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Literal

NodeKind = Literal["physical", "aggregate"]
NodeRole = Literal["core", "dist", "access", "unknown", "stub"]


@dataclass
class TopologyNode:
    node_id: str
    node_kind: NodeKind
    label: str
    site: str
    role: NodeRole
    ip: str = ""
    device_key: str = ""
    hostname: str = ""
    group_id: str = ""
    member_device_keys: list[str] = field(default_factory=list)
    member_count: int = 0
    parent_dist_node_id: str = ""
    platform_model: str = ""  # from CDP Platform on neighbor rows


@dataclass
class TopologyEdge:
    edge_id: str
    source_id: str
    target_id: str
    local_interface: str
    remote_interface: str
    protocol: str
    cable_type: str = "unknown"
    color: str = "#6366f1"
    pair_index: int = 0
    pair_count: int = 1
    underlying_row_ids: list[str] = field(default_factory=list)


def stub_node_id(hostname: str) -> str:
    base = re.sub(r"[^\w.-]+", "-", (hostname or "unknown").split(".")[0].lower())
    return f"hn:{base or 'unknown'}"


def edge_color(edge_id: str) -> str:
    palette = (
        "#6366f1",
        "#22c55e",
        "#f97316",
        "#eab308",
        "#ec4899",
        "#14b8a6",
        "#a855f7",
        "#ef4444",
    )
    h = hashlib.sha256(edge_id.encode()).hexdigest()
    return palette[int(h[:8], 16) % len(palette)]


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _host_alias_keys(name: str) -> set[str]:
    s = (name or "").strip()
    if not s:
        return set()
    short = s.split(".")[0].lower()
    return {s.lower(), short}


def merge_stub_with_inventory_nodes(
    nodes: list[TopologyNode],
    edges: list[TopologyEdge],
) -> tuple[list[TopologyNode], list[TopologyEdge]]:
    """Point hn:* stub edges at inventory physical nodes when hostnames match."""
    physical_by_host: dict[str, str] = {}
    for n in nodes:
        if n.node_kind != "physical" or n.node_id.startswith("hn:"):
            continue
        for key in _host_alias_keys(n.hostname or n.label):
            physical_by_host.setdefault(key, n.node_id)

    remap: dict[str, str] = {}
    for n in nodes:
        if not n.node_id.startswith("hn:"):
            continue
        host = (n.hostname or n.label or n.node_id[3:]).strip()
        for key in _host_alias_keys(host):
            if key in physical_by_host:
                remap[n.node_id] = physical_by_host[key]
                break

    if not remap:
        return nodes, edges

    kept_nodes = [n for n in nodes if n.node_id not in remap]
    new_edges: list[TopologyEdge] = []
    for e in edges:
        src = remap.get(e.source_id, e.source_id)
        tgt = remap.get(e.target_id, e.target_id)
        if src == tgt:
            continue
        new_edges.append(
            TopologyEdge(
                edge_id=e.edge_id,
                source_id=src,
                target_id=tgt,
                local_interface=e.local_interface,
                remote_interface=e.remote_interface,
                protocol=e.protocol,
                cable_type=e.cable_type,
                color=e.color,
                pair_index=e.pair_index,
                pair_count=e.pair_count,
                underlying_row_ids=e.underlying_row_ids,
            )
        )
    return kept_nodes, new_edges


def build_topology_graph(
    devices: list[dict[str, Any]],
    neighbors_by_key: dict[str, list[dict[str, Any]]],
) -> tuple[list[TopologyNode], list[TopologyEdge]]:
    """Build physical nodes and directed edges from catalog-style inputs."""
    nodes: dict[str, TopologyNode] = {}
    edges: list[TopologyEdge] = []

    for d in devices:
        dk = d["device_key"]
        nodes[dk] = TopologyNode(
            node_id=dk,
            node_kind="physical",
            label=d.get("hostname") or dk,
            site=d.get("site") or "",
            role="unknown",
            ip=d.get("ip") or "",
            device_key=dk,
            hostname=d.get("hostname") or "",
        )

    pair_buckets: dict[tuple[str, str], list[int]] = {}

    for src_key, nrows in neighbors_by_key.items():
        if src_key not in nodes:
            site = src_key.split("|")[0] if "|" in src_key else ""
            nodes[src_key] = TopologyNode(
                node_id=src_key,
                node_kind="physical",
                label=src_key,
                site=site,
                role="unknown",
                device_key=src_key,
            )
        for row in nrows:
            tgt_key = row.get("remote_device_key")
            remote_host = row.get("remote_hostname") or ""
            if tgt_key and tgt_key in nodes:
                target_id = tgt_key
            elif tgt_key:
                target_id = tgt_key
                if target_id not in nodes:
                    site = nodes[src_key].site
                    nodes[target_id] = TopologyNode(
                        node_id=target_id,
                        node_kind="physical",
                        label=remote_host or target_id,
                        site=site,
                        role="unknown",
                        device_key=target_id,
                        hostname=remote_host,
                    )
            else:
                target_id = stub_node_id(remote_host)
                if target_id not in nodes:
                    nodes[target_id] = TopologyNode(
                        node_id=target_id,
                        node_kind="physical",
                        label=remote_host or target_id,
                        site=nodes[src_key].site,
                        role="stub",
                        hostname=remote_host,
                    )

            pair = _pair_key(src_key, target_id)
            pair_buckets.setdefault(pair, []).append(len(edges))
            row_id = hashlib.sha256(
                f"{src_key}|{row.get('protocol')}|{row.get('local_interface')}|"
                f"{remote_host}|{row.get('remote_port')}".encode()
            ).hexdigest()[:16]
            edge_id = f"e:{row_id}"
            edges.append(
                TopologyEdge(
                    edge_id=edge_id,
                    source_id=src_key,
                    target_id=target_id,
                    local_interface=row.get("local_interface") or "",
                    remote_interface=row.get("remote_port") or "",
                    protocol=row.get("protocol") or "",
                    cable_type=row.get("cable_type") or "unknown",
                    color=edge_color(edge_id),
                    underlying_row_ids=[row_id],
                )
            )

    for (a, b), idxs in pair_buckets.items():
        count = len(idxs)
        for i, ei in enumerate(sorted(idxs)):
            e = edges[ei]
            edges[ei] = TopologyEdge(
                edge_id=e.edge_id,
                source_id=e.source_id,
                target_id=e.target_id,
                local_interface=e.local_interface,
                remote_interface=e.remote_interface,
                protocol=e.protocol,
                cable_type=e.cable_type,
                color=e.color,
                pair_index=i,
                pair_count=count,
                underlying_row_ids=e.underlying_row_ids,
            )

    return list(nodes.values()), edges
