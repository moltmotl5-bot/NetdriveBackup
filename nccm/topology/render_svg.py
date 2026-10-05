from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from nccm.topology.layout_tree import CELL_H, CELL_W
from nccm.topology.model import TopologyEdge, TopologyNode

ROLE_STYLES = {
    "core": ("#dbeafe", "#2563eb", "#1e40af"),
    "dist": ("#dcfce7", "#16a34a", "#166534"),
    "access": ("#ffedd5", "#ea580c", "#9a3412"),
    "unknown": ("#e2e8f0", "#64748b", "#334155"),
    "stub": ("#f1f5f9", "#94a3b8", "#64748b"),
}

# Longest match first (TenGig* before Ethernet).
_IFACE_PREFIXES = tuple(
    sorted(
        {
            ("TenGigabitEthernet", "Te"),
            ("TenGigE", "Te"),
            ("GigabitEthernet", "Gi"),
            ("GigE", "Gi"),
            ("FastEthernet", "Fa"),
            ("Ethernet", "Eth"),
        },
        key=lambda x: -len(x[0]),
    )
)


@dataclass
class _LabelSpec:
    text: str
    x: float
    y: float
    color: str
    segment_key: tuple


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
    for full, short in _IFACE_PREFIXES:
        if s.lower().startswith(full.lower()):
            return short + s[len(full) :]
    return s


def _orthogonal_path_coords(
    start: tuple[float, float], end: tuple[float, float], pair_index: int
) -> list[tuple[float, float]]:
    x1, y1 = start
    x2, y2 = end
    offset = pair_index * 12
    if abs(x2 - x1) >= abs(y2 - y1):
        mid_x = (x1 + x2) / 2 + offset
        return [(x1, y1), (mid_x, y1), (mid_x, y2), (x2, y2)]
    mid_y = (y1 + y2) / 2 + offset
    return [(x1, y1), (x1, mid_y), (x2, mid_y), (x2, y2)]


def _orthogonal_path_str(coords: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)


def _segment_key(p1: tuple[float, float], p2: tuple[float, float]) -> tuple:
    x1, y1 = p1
    x2, y2 = p2
    if abs(x2 - x1) >= abs(y2 - y1):
        y = round((y1 + y2) / 2)
        return ("H", y, round(min(x1, x2)), round(max(x1, x2)))
    x = round((x1 + x2) / 2)
    return ("V", x, round(min(y1, y2)), round(max(y1, y2)))


def _perpendicular_offset(
    p1: tuple[float, float], p2: tuple[float, float], distance: float, side: int
) -> tuple[float, float]:
    x1, y1 = p1
    x2, y2 = p2
    if abs(x2 - x1) >= abs(y2 - y1):
        return (0.0, -side * distance)
    return (side * distance, 0.0)


def _label_on_segment(
    p1: tuple[float, float],
    p2: tuple[float, float],
    text: str,
    color: str,
    *,
    pair_index: int,
    end: str,
) -> _LabelSpec | None:
    if not text:
        return None
    x1, y1 = p1
    x2, y2 = p2
    seg_len = abs(x2 - x1) + abs(y2 - y1)
    if seg_len < 8:
        return None
    t = 0.35 if end == "source" else 0.65
    mx = x1 + (x2 - x1) * t
    my = y1 + (y2 - y1) * t
    side = 1 if pair_index % 2 == 0 else -1
    if end == "target":
        side = -side
    dist = 12 + pair_index * 3
    ox, oy = _perpendicular_offset(p1, p2, dist, side)
    return _LabelSpec(
        text=text,
        x=mx + ox,
        y=my + oy,
        color=color,
        segment_key=_segment_key(p1, p2),
    )


def _spread_segment_labels(labels: list[_LabelSpec]) -> None:
    """Spread labels that share the same orthogonal segment to avoid overlap."""
    buckets: dict[tuple, list[_LabelSpec]] = defaultdict(list)
    for lab in labels:
        buckets[lab.segment_key].append(lab)

    for key, group in buckets.items():
        if len(group) <= 1:
            continue
        kind = key[0]
        group.sort(key=lambda l: (l.x, l.y))
        n = len(group)
        spacing = 13
        for i, lab in enumerate(group):
            offset_index = i - (n - 1) / 2
            if kind == "H":
                lab.y += offset_index * spacing
            else:
                lab.x += offset_index * spacing


def _resolve_grid_collisions(labels: list[_LabelSpec]) -> None:
    cell = 12
    seen: dict[tuple[int, int], int] = {}
    for lab in labels:
        for attempt in range(10):
            gx = int(round(lab.x / cell))
            gy = int(round(lab.y / cell))
            hits = seen.get((gx, gy), 0)
            if hits == 0:
                seen[(gx, gy)] = 1
                break
            bump = (attempt + 1) * cell * (1 if attempt % 2 == 0 else -1)
            if lab.segment_key[0] == "H":
                lab.y += bump
            else:
                lab.x += bump
            seen[(gx, gy)] = hits + 1


def _collect_edge_labels(e: TopologyEdge, coords: list[tuple[float, float]]) -> list[_LabelSpec]:
    local = _abbrev_ifname(e.local_interface)
    remote = _abbrev_ifname(e.remote_interface)
    if not local and not remote:
        return []
    out: list[_LabelSpec] = []
    if len(coords) >= 2:
        lab = _label_on_segment(
            coords[0],
            coords[1],
            local,
            e.color,
            pair_index=e.pair_index,
            end="source",
        )
        if lab:
            out.append(lab)
    if len(coords) >= 2:
        lab = _label_on_segment(
            coords[-2],
            coords[-1],
            remote,
            e.color,
            pair_index=e.pair_index,
            end="target",
        )
        if lab:
            out.append(lab)
    return out


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
        "<defs><style>.topo-node{cursor:pointer}g.topo-edge-label{opacity:0;"
        "pointer-events:none}svg.topo-labels-visible g.topo-edge-label{opacity:1}"
        ".topo-edge-label text{font-family:system-ui,sans-serif;font-size:8px;"
        "paint-order:stroke fill;stroke:#0b1018;stroke-width:2.5px}</style></defs>",
    ]

    all_labels: list[_LabelSpec] = []

    for e in edges:
        if e.source_id not in positions or e.target_id not in positions:
            continue
        sx, sy = positions[e.source_id]
        tx, ty = positions[e.target_id]
        start, end = _cell_anchor(sx, sy, tx, ty)
        coords = _orthogonal_path_coords(start, end, e.pair_index)
        pts = _orthogonal_path_str(coords)
        dash = "" if not e.target_id.startswith("hn:") else ""
        parts.append(
            f'<polyline points="{pts}" fill="none" stroke="{e.color}" '
            f'stroke-width="2" stroke-linejoin="round" {dash}/>'
        )
        all_labels.extend(_collect_edge_labels(e, coords))

    _spread_segment_labels(all_labels)
    _resolve_grid_collisions(all_labels)

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

    for lab in all_labels:
        w = max(28, len(lab.text) * 4.8)
        h = 11
        rx = lab.x - w / 2
        ry = lab.y - h / 2
        parts.append(
            f'<g class="topo-edge-label">'
            f'<rect x="{rx:.1f}" y="{ry:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="2" fill="#0b1018" fill-opacity="0.88" stroke="{lab.color}" '
            f'stroke-width="0.5"/>'
            f'<text x="{lab.x:.1f}" y="{lab.y:.1f}" text-anchor="middle" '
            f'dominant-baseline="middle" fill="{lab.color}">'
            f"{_esc(_truncate(lab.text, 22))}</text></g>"
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
