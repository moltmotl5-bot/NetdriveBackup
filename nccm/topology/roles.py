from __future__ import annotations

import re

from nccm.topology.model import NodeRole, TopologyNode


def _name_role(hostname: str) -> NodeRole | None:
    h = (hostname or "").upper()
    if re.search(r"\bCORE\b|^CORE-", h):
        return "core"
    if re.search(r"\bDIST\b|^DIST-|\bDSW\b", h):
        return "dist"
    if re.search(r"\bACC\b|^ACC-|\bACCESS\b|\bASW\b", h):
        return "access"
    return None


def infer_roles(nodes: list[TopologyNode], out_degree: dict[str, int]) -> None:
    for n in nodes:
        if n.role == "stub":
            continue
        by_name = _name_role(n.hostname or n.label)
        if by_name:
            n.role = by_name
            continue
        deg = out_degree.get(n.node_id, 0)
        if deg >= 4:
            n.role = "dist"
        elif deg <= 1 and n.node_id.startswith("hn:"):
            n.role = "stub"
        else:
            n.role = "unknown"
