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

LINK_SPACING = 22
FANOUT_SPACING = 18
LABEL_SLOT_PX = 16
LABEL_STUB_PAD = 12
LABEL_COLUMN_GAP = 18
MIN_TWO_LABEL_STUB = 58
MIN_COLUMN_PAIR_STUB = 36
LABEL_CLEARANCE = 4

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
class _Seg:
    p1: tuple[float, float]
    p2: tuple[float, float]

    @property
    def key(self) -> tuple:
        return _segment_key(self.p1, self.p2)

    @property
    def kind(self) -> str:
        return self.key[0]

    @property
    def length(self) -> float:
        x1, y1 = self.p1
        x2, y2 = self.p2
        return abs(x2 - x1) + abs(y2 - y1)


@dataclass
class _LabelSpec:
    text: str
    x: float
    y: float
    color: str
    segment_key: tuple
    rotate: int = 0
    seg: _Seg | None = None
    slot_t: float = 0.5


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
    start: tuple[float, float],
    end: tuple[float, float],
    pair_index: int,
    pair_count: int = 1,
    *,
    channel_offset: float = 0.0,
) -> list[tuple[float, float]]:
    x1, y1 = start
    x2, y2 = end
    center = (max(1, pair_count) - 1) / 2.0
    offset = (pair_index - center) * LINK_SPACING + channel_offset
    if abs(x2 - x1) >= abs(y2 - y1):
        mid_x = (x1 + x2) / 2 + offset
        return [(x1, y1), (mid_x, y1), (mid_x, y2), (x2, y2)]
    mid_y = (y1 + y2) / 2 + offset
    return [(x1, y1), (x1, mid_y), (x2, mid_y), (x2, y2)]


def _fanout_channel_by_edge(
    edges: list[TopologyEdge],
    positions: dict[str, tuple[float, float]],
) -> dict[str, float]:
    """Spread orthogonal channels for multi-homed nodes (e.g. H2 to several DS)."""
    channel: dict[str, float] = defaultdict(float)
    by_src: dict[str, list[TopologyEdge]] = defaultdict(list)
    by_tgt: dict[str, list[TopologyEdge]] = defaultdict(list)
    for e in edges:
        if e.source_id not in positions or e.target_id not in positions:
            continue
        by_src[e.source_id].append(e)
        by_tgt[e.target_id].append(e)

    def _slot_offset(sorted_edges: list[TopologyEdge]) -> None:
        n = len(sorted_edges)
        if n <= 1:
            return
        for i, e in enumerate(sorted_edges):
            channel[e.edge_id] += (i - (n - 1) / 2.0) * FANOUT_SPACING

    for elist in by_src.values():
        elist.sort(
            key=lambda e: (
                positions[e.target_id][0],
                positions[e.target_id][1],
                e.edge_id,
            )
        )
        _slot_offset(elist)
    for elist in by_tgt.values():
        elist.sort(
            key=lambda e: (
                positions[e.source_id][0],
                positions[e.source_id][1],
                e.edge_id,
            )
        )
        _slot_offset(elist)
    return channel


def _vertical_column(x: float) -> int:
    return int(round(x / 12.0))


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


def _segments_from_coords(coords: list[tuple[float, float]]) -> list[_Seg]:
    segs: list[_Seg] = []
    for i in range(len(coords) - 1):
        seg = _Seg(coords[i], coords[i + 1])
        if seg.length >= 6:
            segs.append(seg)
    return segs


def _pick_source_segment(segs: list[_Seg]) -> _Seg | None:
    if not segs:
        return None
    verticals = [s for s in segs if s.kind == "V"]
    if verticals:
        return verticals[0]
    return segs[0]


def _pick_target_segment(segs: list[_Seg]) -> _Seg | None:
    """Prefer vertical drop into core/dist; avoid crowded horizontal trunks."""
    if not segs:
        return None
    verticals = [s for s in segs if s.kind == "V"]
    if verticals:
        return verticals[-1]
    return segs[-1]


def _point_on_segment(seg: _Seg, t: float) -> tuple[float, float]:
    x1, y1 = seg.p1
    x2, y2 = seg.p2
    return (x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)


def _label_on_wire(
    seg: _Seg,
    text: str,
    color: str,
    *,
    t: float = 0.5,
) -> _LabelSpec | None:
    if not text or seg.length < 8:
        return None
    x, y = _point_on_segment(seg, t)
    rotate = -90 if seg.kind == "V" else 0
    return _LabelSpec(
        text=text,
        x=x,
        y=y,
        color=color,
        segment_key=seg.key,
        rotate=rotate,
        seg=seg,
        slot_t=t,
    )


def _same_segment(a: _Seg, b: _Seg) -> bool:
    return a.key == b.key and a.p1 == b.p1 and a.p2 == b.p2


def _label_stack_extent(lab: _LabelSpec) -> float:
    """Vertical span of a port capsule on the canvas (rotated labels use text width)."""
    w = max(26, len(lab.text) * 4.6)
    return w if lab.rotate else 10


def _required_stub_length(label_count: int, *, max_text_len: int = 12) -> float:
    if label_count >= 2:
        extent = max(26, max_text_len * 4.6)
        # Same-segment spread uses t=(i+1)/(n+1); need Δt >= stacked extents on the wire.
        spread_gap_t = 1.0 / (label_count + 1)
        by_extent = (2 * extent + LABEL_CLEARANCE) / max(spread_gap_t, 0.25)
        return max(
            MIN_TWO_LABEL_STUB,
            by_extent,
            label_count * LABEL_COLUMN_GAP + LABEL_STUB_PAD + 8,
        )
    return LABEL_COLUMN_GAP + LABEL_STUB_PAD


def _extend_column_pair_stubs(
    coords: list[tuple[float, float]], segs: list[_Seg], n_labels: int
) -> list[tuple[float, float]]:
    """Two ports on one vertical column (lower + upper stub), e.g. DS under H2."""
    v_idxs = [i for i, s in enumerate(segs) if s.kind == "V"]
    if n_labels < 2 or len(v_idxs) < 2:
        return coords
    pts = [list(p) for p in coords]

    def _lengthen_stub(seg_idx: int, need_len: float) -> None:
        seg = segs[seg_idx]
        extra = max(0.0, need_len - seg.length)
        if extra <= 0:
            return
        i = seg_idx
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        dy = y2 - y1
        if abs(dy) < 1:
            return
        sign = 1 if dy > 0 else -1
        if seg_idx == 0:
            pts[i + 1][1] = y2 + sign * extra
            for j in range(i + 2, len(pts)):
                if abs(pts[j][0] - pts[i + 1][0]) < 0.5 or abs(pts[j][1] - y2) < 0.5:
                    pts[j][1] = pts[i + 1][1]
        elif seg_idx == len(segs) - 1:
            pts[i][1] = y1 - sign * extra
            if i > 0 and abs(pts[i - 1][1] - y1) < 0.5:
                pts[i - 1][1] = pts[i][1]
        else:
            pts[i + 1][1] = y2 + sign * extra

    per_stub = max(MIN_COLUMN_PAIR_STUB, _required_stub_length(2) * 0.55)
    for vi in v_idxs:
        _lengthen_stub(vi, per_stub)

    return [tuple(p) for p in pts]


def _extend_coords_for_labels(
    coords: list[tuple[float, float]],
    segs: list[_Seg],
    label_count_by_idx: dict[int, int],
    *,
    column_pair: bool = False,
    column_label_count: int = 0,
) -> list[tuple[float, float]]:
    """Lengthen vertical stubs so port labels fit along the wire without stacking."""
    if column_pair and column_label_count >= 2:
        return _extend_column_pair_stubs(coords, segs, column_label_count)
    if not label_count_by_idx:
        return coords
    pts = [list(p) for p in coords]
    for seg_idx, n in sorted(label_count_by_idx.items()):
        if n <= 0 or seg_idx >= len(segs):
            continue
        seg = segs[seg_idx]
        if seg.kind != "V":
            continue
        need_len = _required_stub_length(n)
        extra = max(0.0, need_len - seg.length)
        if extra <= 0:
            continue
        i = seg_idx
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        dy = y2 - y1
        if abs(dy) < 1:
            continue
        sign = 1 if dy > 0 else -1
        if seg_idx == 0:
            pts[i + 1][1] = y2 + sign * extra
            for j in range(i + 2, len(pts)):
                if abs(pts[j][0] - pts[i + 1][0]) < 0.5:
                    pts[j][1] = pts[i + 1][1]
                elif abs(pts[j][1] - y2) < 0.5:
                    pts[j][1] = pts[i + 1][1]
        elif seg_idx == len(segs) - 1:
            pts[i][1] = y1 - sign * extra
            if i > 0 and abs(pts[i - 1][1] - y1) < 0.5:
                pts[i - 1][1] = pts[i][1]
        else:
            pts[i + 1][1] = y2 + sign * extra
    return [tuple(p) for p in pts]


def _label_plan(
    segs: list[_Seg], local: str, remote: str
) -> tuple[dict[int, int], list[tuple[int, str, float]], bool, int]:
    """Return counts, placements, column_pair flag, labels on shared vertical column."""
    counts: dict[int, int] = defaultdict(int)
    placements: list[tuple[int, str, float]] = []
    column_pair = False
    column_labels = 0
    src = _pick_source_segment(segs)
    tgt = _pick_target_segment(segs)
    if not local and not remote:
        return counts, placements, column_pair, column_labels
    if src and tgt and _same_segment(src, tgt):
        idx = segs.index(src)
        n = int(bool(local)) + int(bool(remote))
        counts[idx] = n
        column_labels = n
        if local:
            placements.append((idx, local, 0.2 if n >= 2 else 0.5))
        if remote:
            placements.append((idx, remote, 0.8 if n >= 2 else 0.5))
        return counts, placements, column_pair, column_labels
    if (
        local
        and remote
        and src
        and tgt
        and src.kind == "V"
        and tgt.kind == "V"
        and _vertical_column((src.p1[0] + src.p2[0]) / 2)
        == _vertical_column((tgt.p1[0] + tgt.p2[0]) / 2)
    ):
        column_pair = True
        column_labels = 2
        sidx = segs.index(src)
        tidx = segs.index(tgt)
        counts[sidx] = 1
        counts[tidx] = 1
        placements.append((sidx, local, 0.18))
        placements.append((tidx, remote, 0.82))
        return counts, placements, column_pair, column_labels
    if local and src:
        idx = segs.index(src)
        counts[idx] += 1
        column_labels += 1
        placements.append((idx, local, 0.32))
    if remote and tgt:
        idx = segs.index(tgt)
        counts[idx] += 1
        column_labels += 1
        placements.append((idx, remote, 0.68))
    return counts, placements, column_pair, column_labels


def _spread_segment_labels(labels: list[_LabelSpec]) -> None:
    """Place labels along the wire (vary t) when they share the same segment."""
    buckets: dict[tuple, list[_LabelSpec]] = defaultdict(list)
    for lab in labels:
        buckets[lab.segment_key].append(lab)

    for group in buckets.values():
        if len(group) <= 1:
            continue
        group.sort(key=lambda l: (l.y, l.x))
        n = len(group)
        seg = group[0].seg
        if not seg or seg.length < 8:
            continue
        if n == 2 and seg.kind == "V" and all(l.rotate == -90 for l in group):
            e0 = _label_stack_extent(group[0])
            e1 = _label_stack_extent(group[1])
            half = (e0 + e1) / (2 * seg.length) + LABEL_CLEARANCE / seg.length
            half = min(max(half, 0.22), 0.38)
            ts = (0.5 - half, 0.5 + half)
            for lab, t in zip(group, ts):
                lab.slot_t = t
                lab.x, lab.y = _point_on_segment(seg, t)
            continue
        for i, lab in enumerate(group):
            t = (i + 1) / (n + 1)
            lab.slot_t = t
            x, y = _point_on_segment(seg, t)
            lab.x, lab.y = x, y


def _nudge_vertical_column_labels(labels: list[_LabelSpec]) -> None:
    """Separate rotated port labels that share the same vertical wire column."""
    cols: dict[int, list[_LabelSpec]] = defaultdict(list)
    for lab in labels:
        if lab.rotate == -90:
            cols[_vertical_column(lab.x)].append(lab)
    for group in cols.values():
        if len(group) <= 1:
            continue
        group.sort(key=lambda l: l.y)
        for i in range(1, len(group)):
            need = (_label_stack_extent(group[i - 1]) + _label_stack_extent(group[i])) / 2
            need += LABEL_CLEARANCE
            gap = group[i].y - group[i - 1].y
            if gap < need:
                group[i].y = group[i - 1].y + need


def _global_vertical_label_counts(
    edge_plans: list[tuple[dict[int, int], list[_Seg]]],
) -> dict[int, int]:
    """Count labels per vertical column (x bucket) for stub lengthening."""
    col_counts: dict[int, int] = defaultdict(int)
    for counts, segs in edge_plans:
        for idx, n in counts.items():
            if idx >= len(segs) or n <= 0:
                continue
            seg = segs[idx]
            if seg.kind != "V":
                continue
            col_counts[_vertical_column((seg.p1[0] + seg.p2[0]) / 2)] += n
    return col_counts


def _merge_vertical_counts(
    local: dict[int, int], segs: list[_Seg], global_col: dict[int, int]
) -> dict[int, int]:
    merged = dict(local)
    for idx, n in list(local.items()):
        if idx >= len(segs):
            continue
        seg = segs[idx]
        if seg.kind != "V":
            continue
        col = _vertical_column((seg.p1[0] + seg.p2[0]) / 2)
        g = global_col.get(col, n)
        merged[idx] = max(n, g)
    return merged


def _labels_from_plan(
    e: TopologyEdge,
    coords: list[tuple[float, float]],
    placements: list[tuple[int, str, float]],
) -> list[_LabelSpec]:
    segs = _segments_from_coords(coords)
    out: list[_LabelSpec] = []
    for seg_idx, text, t in placements:
        if not text or seg_idx >= len(segs):
            continue
        lab = _label_on_wire(segs[seg_idx], text, e.color, t=t)
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

    visible = [e for e in edges if e.source_id in positions and e.target_id in positions]
    channel_by_edge = _fanout_channel_by_edge(visible, positions)

    prep: list[tuple[TopologyEdge, list[tuple[float, float]], dict[int, int], list[tuple[int, str, float]]]] = []
    plan_for_global: list[tuple[dict[int, int], list[_Seg]]] = []

    for e in visible:
        sx, sy = positions[e.source_id]
        tx, ty = positions[e.target_id]
        start, end = _cell_anchor(sx, sy, tx, ty)
        coords = _orthogonal_path_coords(
            start,
            end,
            e.pair_index,
            pair_count=max(1, e.pair_count),
            channel_offset=channel_by_edge.get(e.edge_id, 0.0),
        )
        local = _abbrev_ifname(e.local_interface)
        remote = _abbrev_ifname(e.remote_interface)
        segs = _segments_from_coords(coords)
        counts, placements, column_pair, column_labels = _label_plan(segs, local, remote)
        plan_for_global.append((dict(counts), segs))
        prep.append((e, coords, counts, placements, column_pair, column_labels))

    global_col = _global_vertical_label_counts(plan_for_global)

    all_labels: list[_LabelSpec] = []
    draw_queue: list[tuple[TopologyEdge, list[tuple[float, float]]]] = []

    for e, coords, counts, placements, column_pair, column_labels in prep:
        segs = _segments_from_coords(coords)
        merged = _merge_vertical_counts(counts, segs, global_col)
        coords = _extend_coords_for_labels(
            coords,
            segs,
            merged,
            column_pair=column_pair,
            column_label_count=column_labels,
        )
        draw_queue.append((e, coords))
        all_labels.extend(_labels_from_plan(e, coords, placements))

    _spread_segment_labels(all_labels)
    _nudge_vertical_column_labels(all_labels)

    for e, coords in draw_queue:
        pts = _orthogonal_path_str(coords)
        dash = "" if not e.target_id.startswith("hn:") else ""
        parts.append(
            f'<polyline points="{pts}" fill="none" stroke="{e.color}" '
            f'stroke-width="2" stroke-linejoin="round" {dash}/>'
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

    for lab in all_labels:
        w = max(26, len(lab.text) * 4.6)
        h = 10
        rot = f' transform="rotate({lab.rotate} {lab.x:.1f} {lab.y:.1f})"' if lab.rotate else ""
        rx = lab.x - w / 2
        ry = lab.y - h / 2
        parts.append(
            f'<g class="topo-edge-label"{rot}>'
            f'<rect x="{rx:.1f}" y="{ry:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="2" fill="#0b1018" fill-opacity="0.92" stroke="{lab.color}" '
            f'stroke-width="0.75"/>'
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
