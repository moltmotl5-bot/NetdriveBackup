from __future__ import annotations

import pytest

from nccm.switchmap import vlan_colors as vc


@pytest.fixture(autouse=True)
def _isolated_auth_db(tmp_path, monkeypatch):
    db = tmp_path / "vlan_auth.db"
    monkeypatch.setenv("NCCM_AUTH_DB", str(db))
    vc.init_vlan_color_db()


def test_assign_unique_pairs_per_site():
    first = vc.assign_vlan_colors("site-a", [1, 10, 20])
    second = vc.assign_vlan_colors("site-a", [1, 10, 20, 30])
    pairs = {(v["fill"], v["text"]) for v in second.values()}
    assert len(pairs) == len(second)
    assert first["1"] == second["1"]


def test_assigned_pairs_meet_wcag():
    colors = vc.assign_vlan_colors("wcag-site", [100, 101, 102])
    for entry in colors.values():
        assert vc.pair_meets_wcag_aa(entry["fill"], entry["text"])


def test_exhaustion_raises():
    many = list(range(1, 500))
    with pytest.raises(RuntimeError):
        vc.assign_vlan_colors("overflow-site", many)
