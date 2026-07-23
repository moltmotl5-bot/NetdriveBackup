"""Site neighbor topology graph for interactive map."""
from __future__ import annotations

from dataclasses import dataclass

from nccm.inventory.neighbors import neighbor_device_rows, neighbors_for_device
from nccm.parsers.cdp_lldp import normalize_hostname
from nccm.storage.index_db import list_inventory_display


@dataclass(frozen=True)
class TopoNode:
    id: str
    label: str
    vendor: str
    ip: str
    site: str


@dataclass(frozen=True)
class TopoEdge:
    source: str
    target: str
    local_if: str
    remote_if: str
    proto: str


def build_topology(*, site: str = "", vendor: str = "", limit_devices: int = 80) -> dict:
    """Build nodes/edges from latest LLDP/CDP per inventory device."""
    rows = list_inventory_display(query="", site=site, vendor=vendor, limit=limit_devices)
    anchors = [r for r in rows if r.is_config_anchor] or list(rows)

    nodes_map: dict[str, TopoNode] = {}
    edges: list[TopoEdge] = []
    seen_e: set[tuple[str, str, str]] = set()

    host_to_id: dict[str, str] = {}
    for r in anchors:
        nid = r.device_id
        nodes_map[nid] = TopoNode(
            id=nid,
            label=r.hostname or r.ip,
            vendor=r.vendor or "",
            ip=r.ip or "",
            site=r.site or "",
        )
        if r.hostname:
            host_to_id[normalize_hostname(r.hostname)] = nid

    _, lookup = neighbor_device_rows(query="", site=site, vendor=vendor)

    for r in anchors:
        try:
            neigh, _cdp, _lldp, _ver = neighbors_for_device(
                r.device_id, snapshot_ts="", lookup=lookup
            )
        except Exception:
            continue
        for n in neigh or []:
            if not isinstance(n, dict):
                continue
            remote = str(n.get("remote_hostname") or "").strip()
            if not remote:
                continue
            local_if = str(n.get("local_interface") or "")
            remote_if = str(n.get("remote_port") or "")
            proto = str(n.get("protocol") or "LLDP")
            rkey = n.get("remote_device_key")
            tid = None
            if rkey and isinstance(rkey, str) and rkey in nodes_map:
                tid = rkey
            if not tid:
                tid = host_to_id.get(normalize_hostname(remote))
            if not tid:
                tid = f"ext::{remote}"
                if tid not in nodes_map:
                    nodes_map[tid] = TopoNode(
                        id=tid, label=remote, vendor="", ip="", site=r.site or ""
                    )
            ek = (r.device_id, tid, local_if)
            if ek in seen_e:
                continue
            seen_e.add(ek)
            edges.append(
                TopoEdge(
                    source=r.device_id,
                    target=tid,
                    local_if=local_if,
                    remote_if=remote_if,
                    proto=proto,
                )
            )

    return {
        "nodes": [n.__dict__ for n in nodes_map.values()],
        "edges": [e.__dict__ for e in edges],
        "site": site,
        "node_count": len(nodes_map),
        "edge_count": len(edges),
    }
