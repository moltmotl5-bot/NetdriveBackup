"""Persistent unique VLAN fill + text color pairs per site (SwitchMap Phase 3)."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from nccm.config import auth_db_path

# Fill palette; text color chosen per fill to satisfy WCAG AA.
_VLAN_FILL_PALETTE: tuple[str, ...] = (
    "#4E79A7",
    "#F28E2B",
    "#E15759",
    "#76B7B2",
    "#59A14F",
    "#EDC948",
    "#B07AA1",
    "#FF9DA7",
    "#9C755F",
    "#BAB0AC",
    "#86BCB6",
    "#D37295",
    "#FABFD2",
    "#8CD17D",
    "#B6992D",
    "#499894",
    "#79706E",
    "#D4A6C8",
    "#FFBE7D",
    "#AEC7E8",
    "#1F77B4",
    "#FF7F0E",
    "#2CA02C",
    "#D62728",
    "#9467BD",
    "#8C564B",
    "#E377C2",
    "#7F7F7F",
    "#BCBD22",
    "#17BECF",
    "#393B79",
    "#637939",
    "#8C6D31",
    "#843C39",
    "#7B4173",
    "#5254A3",
    "#6B6ECF",
    "#9C9EDE",
    "#B5CF6B",
    "#C49C94",
    "#F7B6D2",
    "#C7C7C7",
    "#DBDB8D",
    "#9EDAE5",
    "#AD494A",
    "#8C6239",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vlan_color_assignments (
    site TEXT NOT NULL,
    vlan_id INTEGER NOT NULL,
    fill_hex TEXT NOT NULL,
    text_hex TEXT NOT NULL,
    PRIMARY KEY (site, vlan_id)
);
CREATE INDEX IF NOT EXISTS idx_vlan_color_site ON vlan_color_assignments(site);
"""


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (0.0, 0.0, 0.0)
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return (r, g, b)


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fill_hex: str, text_hex: str) -> float:
    l1 = _relative_luminance(_hex_to_rgb(fill_hex))
    l2 = _relative_luminance(_hex_to_rgb(text_hex))
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def pair_meets_wcag_aa(fill_hex: str, text_hex: str) -> bool:
    return contrast_ratio(fill_hex, text_hex) >= 4.5


def best_text_color_for_fill(fill_hex: str) -> str:
    for candidate in ("#FFFFFF", "#1A1A1A", "#000000"):
        if pair_meets_wcag_aa(fill_hex, candidate):
            return candidate
    return "#1A1A1A"


def ensure_wcag_pair(fill_hex: str, text_hex: str | None = None) -> tuple[str, str]:
    """Return fill + text with WCAG AA contrast (dark fill → light text, etc.)."""
    fill = (fill_hex or "").strip() or "#79706E"
    if not fill.startswith("#"):
        fill = f"#{fill}"
    text = (text_hex or "").strip() or best_text_color_for_fill(fill)
    if not text.startswith("#"):
        text = f"#{text}"
    if pair_meets_wcag_aa(fill, text):
        return fill, text
    return fill, best_text_color_for_fill(fill)


def init_vlan_color_db() -> None:
    path = auth_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    init_vlan_color_db()
    conn = sqlite3.connect(auth_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _used_pairs(conn: sqlite3.Connection, site: str) -> set[tuple[str, str]]:
    rows = conn.execute(
        "SELECT fill_hex, text_hex FROM vlan_color_assignments WHERE site = ?",
        (site,),
    ).fetchall()
    return {(str(r["fill_hex"]).upper(), str(r["text_hex"]).upper()) for r in rows}


def _next_free_pair(used: set[tuple[str, str]]) -> tuple[str, str] | None:
    for fill in _VLAN_FILL_PALETTE:
        text = best_text_color_for_fill(fill)
        key = (fill.upper(), text.upper())
        if key not in used:
            return fill, text
    return None


def get_vlan_colors_for_site(site: str) -> dict[str, dict[str, str]]:
    site_key = (site or "").strip() or "_default"
    with _connect() as conn:
        rows = conn.execute(
            "SELECT vlan_id, fill_hex, text_hex FROM vlan_color_assignments WHERE site = ? ORDER BY vlan_id",
            (site_key,),
        ).fetchall()
    return {
        str(int(r["vlan_id"])): {"fill": r["fill_hex"], "text": r["text_hex"]}
        for r in rows
    }


def assign_vlan_colors(site: str, vlan_ids: list[int | str]) -> dict[str, dict[str, str]]:
    """Return color map for vlan_ids, allocating persistent unique pairs per site."""
    site_key = (site or "").strip() or "_default"
    normalized: list[int] = []
    for vid in vlan_ids:
        try:
            normalized.append(int(str(vid).strip()))
        except ValueError:
            continue
    normalized = sorted(set(normalized))

    with _connect() as conn:
        existing = {
            int(r["vlan_id"]): {"fill": r["fill_hex"], "text": r["text_hex"]}
            for r in conn.execute(
                "SELECT vlan_id, fill_hex, text_hex FROM vlan_color_assignments WHERE site = ?",
                (site_key,),
            ).fetchall()
        }
        used = _used_pairs(conn, site_key)
        result: dict[str, dict[str, str]] = {}

        for vid in normalized:
            if vid in existing:
                fill, text = ensure_wcag_pair(
                    existing[vid]["fill"], existing[vid]["text"]
                )
                if fill != existing[vid]["fill"] or text != existing[vid]["text"]:
                    conn.execute(
                        "UPDATE vlan_color_assignments SET fill_hex = ?, text_hex = ? "
                        "WHERE site = ? AND vlan_id = ?",
                        (fill, text, site_key, vid),
                    )
                    existing[vid] = {"fill": fill, "text": text}
                result[str(vid)] = existing[vid]
                continue
            pair = _next_free_pair(used)
            if pair is None:
                raise RuntimeError(
                    f"VLAN 配色表已用盡（site={site_key!r}，已配置 {len(used)} 組）。"
                )
            fill, text = pair
            conn.execute(
                "INSERT INTO vlan_color_assignments (site, vlan_id, fill_hex, text_hex) VALUES (?, ?, ?, ?)",
                (site_key, vid, fill, text),
            )
            used.add((fill.upper(), text.upper()))
            existing[vid] = {"fill": fill, "text": text}
            result[str(vid)] = existing[vid]

        return result
