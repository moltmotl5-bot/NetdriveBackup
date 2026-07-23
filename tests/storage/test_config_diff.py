from __future__ import annotations

from nccm.storage.config_diff import config_sha256, diff_configs

from conftest import read_fixture


def test_diff_detects_description_change():
    a = read_fixture("config/cfg_a.txt")
    b = read_fixture("config/cfg_b.txt")
    assert config_sha256(a) != config_sha256(b)
    u = diff_configs(a, b, fromfile="a", tofile="b")
    assert "old-ap" in u and "new-ap" in u
    assert u.startswith("---") or "--- a" in u or u.startswith("---")


def test_diff_identical():
    a = read_fixture("config/cfg_a.txt")
    u = diff_configs(a, a)
    assert u == ""
