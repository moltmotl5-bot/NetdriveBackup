from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# UI / product version shown beside the Portal page title (semver-ish, independent of NCCM v3).
TOPOLOGY_EXPLORER_VERSION = "0.3.1"

from nccm.inventory.neighbors import (
    build_hostname_lookup,
    neighbor_device_rows,
    neighbors_for_device,
)
from nccm.storage.index_db import list_inventory_display, list_sites
from nccm.topology.aggregate import apply_access_aggregation, attach_remote_platform
from nccm.topology.layout_tree import canvas_size, tree_layout
from nccm.topology.model import TopologyEdge, TopologyNode, build_topology_graph
from nccm.topology.render_svg import render_topology_svg
from nccm.topology.roles import infer_roles


@dataclass
class ExplorerView:
    site: str
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]
    svg: str
    total_nodes_physical: int
    current_view_nodes: int
    neighbor_table: list[dict[str, Any]] = field(default_factory=list)
    width: float = 800.0
    height: float = 600.0


def _collect_site_data(site: str) -> tuple[list[dict], dict[str, list[dict]], list[dict]]:
    rows, lookup = neighbor_device_rows(site=site)
    devices = [
        {
            "device_key": r["device_key"],
            "site": r["site"],
            "ip": r["ip"],
            "hostname": r["hostname"],
        }
        for r in rows
    ]
    neighbors_by_key: dict[str, list[dict]] = {}
    table: list[dict[str, Any]] = []
    for r in rows:
        dk = r["device_key"]
        nrows, _cdp, _lldp, _ver = neighbors_for_device(dk, lookup=lookup)
        neighbors_by_key[dk] = nrows
        for n in nrows:
            table.append(
                {
                    "site": r["site"],
                    "local_device": f"{r['hostname']} ({r['ip']})",
                    "device_key": dk,
                    "local_interface": n.get("local_interface"),
                    "protocol": n.get("protocol"),
                    "remote_hostname": n.get("remote_hostname"),
                    "remote_port": n.get("remote_port"),
                    "platform_raw": n.get("platform_raw") or "",
                    "platform_model": n.get("platform_model") or "",
                    "cable_type": n.get("cable_type"),
                    "in_inventory": bool(n.get("remote_device_key")),
                }
            )
    return devices, neighbors_by_key, table


def build_explorer_view(
    *,
    site: str,
    aggregate: bool = True,
    selected_node_id: str = "",
) -> ExplorerView:
    devices, neighbors_by_key, table = _collect_site_data(site)
    physical_nodes, edges = build_topology_graph(devices, neighbors_by_key)
    attach_remote_platform(physical_nodes, edges, neighbors_by_key)
    out_deg: dict[str, int] = {}
    for e in edges:
        out_deg[e.source_id] = out_deg.get(e.source_id, 0) + 1
    infer_roles(physical_nodes, out_deg)
    total_physical = len(physical_nodes)
    nodes, edges = apply_access_aggregation(
        physical_nodes, edges, enabled=aggregate, collapse_threshold=2
    )
    positions = tree_layout(nodes, edges)
    w, h = canvas_size(positions)
    svg = render_topology_svg(
        nodes, edges, positions, w, h, selected_node_id=selected_node_id
    )
    return ExplorerView(
        site=site,
        nodes=nodes,
        edges=edges,
        svg=svg,
        total_nodes_physical=total_physical,
        current_view_nodes=len(nodes),
        neighbor_table=table,
        width=w,
        height=h,
    )


def node_detail_rows(
    view: ExplorerView,
    node_id: str,
    *,
    lookup: dict[str, str] | None = None,
) -> tuple[TopologyNode | None, list[dict[str, Any]]]:
    if lookup is None:
        lookup = build_hostname_lookup(list_inventory_display(site=view.site))
    node = next((n for n in view.nodes if n.node_id == node_id), None)
    if not node:
        return None, []

    rows: list[dict[str, Any]] = []
    if node.node_kind == "aggregate":
        for mk in node.member_device_keys:
            nrows, _, _, _ = neighbors_for_device(mk, lookup=lookup)
            for n in nrows:
                rows.append(
                    {
                        "local_interface": n.get("local_interface"),
                        "remote_hostname": n.get("remote_hostname"),
                        "remote_port": n.get("remote_port"),
                        "protocol": n.get("protocol"),
                        "platform_raw": n.get("platform_raw") or "",
                        "platform_model": n.get("platform_model") or "",
                    }
                )
        return node, rows[:40]

    if node.device_key:
        nrows, _, _, _ = neighbors_for_device(node.device_key, lookup=lookup)
        for n in nrows:
            rows.append(
                {
                    "local_interface": n.get("local_interface"),
                    "remote_hostname": n.get("remote_hostname"),
                    "remote_port": n.get("remote_port"),
                    "protocol": n.get("protocol"),
                    "platform_raw": n.get("platform_raw") or "",
                    "platform_model": n.get("platform_model") or "",
                }
            )
    return node, rows


def list_topology_sites() -> list[str]:
    return list_sites()
