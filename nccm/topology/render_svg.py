from __future__ import annotations

from nccm.topology.layout_tree import CELL_H, CELL_W
from nccm.topology.model import TopologyEdge, TopologyNode

ROLE_STYLES = {
    "core": ("#dbeafe", "#2563eb", "#1e40af"),
    "dist": ("#dcfce7", "#16a34a", "#166534"),
    "access": ("#ffedd5", "#ea580c", "#9a3412"),
    "unknown": ("#e2e8f0", "#64748b", "#334155"),
    "stub": ("#f1f5f9", "#94a3b8", "#64748b"),
}


def _cell_anchor(
    sx: float, sy: float, tx: float, ty: float
) -> tuple[tuple[float, float], tuple[float, float]]:
    cx_s, cy_s = sx + CELL_W / 2, sy + CELL_H / 2
    cx_t, cy_t = tx + CELL_W / 2, ty + CELL_H / 2
    dx, dy = cx_t - cx_s, cy_t - cy_s
    if abs(dx) >= abs(dy):
        start = (cx_s + (CELL_W / 2 if dx > 0 else -CELL_W / 2), cy_s)
        end = (cx_t + (-CELL_W / 2 if dx > 0 else CELL_W / 2), cy_t)
    else:
        start = (cx_s, cy_s + (CELL_H / 2 if dy > 0 else -CELL_H / 2))
        end = (cx_t, cy_t + (-CELL_H / 2 if dy > 0 else CELL_H / 2))
    return start, end


def _abbrev_ifname(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return ""
    pairs = (
        ("TenGigabitEthernet", "Te"),
        ("GigabitEthernet", "Gi"),
        ("FastEthernet", "Fa"),
        ("Ethernet", "Eth"),
        ("TenGigE", "Te"),
        ("GigE", "Gi"),
    )
    for full, short in pairs:
        if s.lower().startswith(full.lower()):
            return short + s[len(full) :]
    return s


def _edge_port_label(local: str, remote: str) -> str:
    loc = _abbrev_ifname(local)
    rem = _abbrev_ifname(remote)
    if loc and rem:
        return f"{loc} ↔ {rem}"
    return loc or rem


def _polyline_midpoint(points: str) -> tuple[float, float] | None:
    tokens = points.replace(",", " ").split()
    coords: list[tuple[float, float]] = []
    for i in range(0, len(tokens) - 1, 2):
        try:
            coords.append((float(tokens[i]), float(tokens[i + 1])))
        except (ValueError, IndexError):
            continue
    if len(coords) < 2:
        return None
    best_len = -1.0
    mid: tuple[float, float] = coords[0]
    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        seg_len = abs(x2 - x1) + abs(y2 - y1)
        if seg_len > best_len:
            best_len = seg_len
            mid = ((x1 + x2) / 2, (y1 + y2) / 2)
    return mid


def _orthogonal_path(
    start: tuple[float, float], end: tuple[float, float], pair_index: int
) -> str:
    x1, y1 = start
    x2, y2 = end
    offset = (pair_index - 0) * 12
    if abs(x2 - x1) >= abs(y2 - y1):
        mid_x = (x1 + x2) / 2 + offset
        pts = [(x1, y1), (mid_x, y1), (mid_x, y2), (x2, y2)]
    else:
        mid_y = (y1 + y2) / 2 + offset
        pts = [(x1, y1), (x1, mid_y), (x2, mid_y), (x2, y2)]
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def render_topology_svg(
    nodes: list[TopologyNode],
    edges: list[TopologyEdge],
    positions: dict[str, tuple[float, float]],
    width: float,
    height: float,
    *,
    selected_node_id: str = "",
) -> str:
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'width="{width:.0f}" height="{height:.0f}" role="img" aria-label="CDP LLDP topology">',
        "<defs><style>.topo-node{cursor:pointer}.topo-edge-label{"
        "font-family:system-ui,sans-serif;font-size:9px;opacity:0;"
        "pointer-events:none;paint-order:stroke fill;stroke:#0b1018;stroke-width:3px}"
        "svg.topo-labels-visible .topo-edge-label{opacity:1}</style></defs>",
    ]

    for e in edges:
        if e.source_id not in positions or e.target_id not in positions:
            continue
        sx, sy = positions[e.source_id]
        tx, ty = positions[e.target_id]
        start, end = _cell_anchor(sx, sy, tx, ty)
        pts = _orthogonal_path(start, end, e.pair_index)
        dash = "" if e.target_id.startswith("hn:") is False else ""
        parts.append(
            f'<polyline points="{pts}" fill="none" stroke="{e.color}" '
            f'stroke-width="2" stroke-linejoin="round" {dash}/>'
        )
        port_label = _edge_port_label(e.local_interface, e.remote_interface)
        if port_label:
            mid = _polyline_midpoint(pts)
            if mid:
                mx, my = mid
                parts.append(
                    f'<text class="topo-edge-label" x="{mx:.1f}" y="{my:.1f}" '
                    f'text-anchor="middle" dominant-baseline="middle" fill="{e.color}">'
                    f"{_esc(_truncate(port_label, 28))}</text>"
                )

    for n in nodes:
        if n.node_id not in positions:
            continue
        x, y = positions[n.node_id]
        fill, stroke, text = ROLE_STYLES.get(n.role, ROLE_STYLES["unknown"])
        if n.node_kind == "aggregate":
            fill, stroke, text = ROLE_STYLES["access"]
        sel = n.node_id == selected_node_id
        sw = 3 if sel else 2
        dash = ' stroke-dasharray="6 3"' if n.node_kind == "aggregate" or n.role == "stub" else ""
        parts.append(
            f'<g class="topo-node" data-topo-node="{_esc(n.node_id)}">'
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{CELL_W}" height="{CELL_H}" '
            f'rx="6" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{dash}/>'
            f'<text x="{x + 8:.1f}" y="{y + 28:.1f}" fill="{text}" '
            f'font-family="system-ui,sans-serif" font-size="12" font-weight="600">'
            f"{_esc(_truncate(n.label, 16))}</text></g>"
        )

    parts.append("</svg>")
    return "\n".join(parts)


def _esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace('"', "&quot;")
    )


def _truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"
