from __future__ import annotations

import os

import pytest

from nccm.registry.csv_validation import validate_ip, validate_port, validate_site


@pytest.fixture(autouse=True)
def _ports(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NCCM_ALLOWED_SSH_PORTS", "22,2222,830")


def test_site_valid():
    assert validate_site("lab-01") == "lab-01"
    assert validate_site("Site.A_1") == "Site.A_1"


@pytest.mark.parametrize(
    "site",
    ["", "../tmp", "a/b", "x..y", "..", "bad space", "x\\y"],
)
def test_site_rejects(site: str):
    with pytest.raises(ValueError):
        validate_site(site)


def test_ip_valid():
    assert validate_ip("10.0.0.1") == "10.0.0.1"
    assert validate_ip("2001:db8::1") == "2001:db8::1"


@pytest.mark.parametrize("ip", ["", "999.1.1.1", "not-an-ip"])
def test_ip_rejects(ip: str):
    with pytest.raises(ValueError):
        validate_ip(ip)


def test_port_allowlist():
    assert validate_port(None) == 22
    assert validate_port("2222") == 2222
    assert validate_port(830) == 830


@pytest.mark.parametrize("port", [0, 65536, 80, 443])
def test_port_rejects(port):
    with pytest.raises(ValueError):
        validate_port(port)


def test_csv_load_rejects_traversal(tmp_path):
    from nccm.registry.csv import load_devices_csv

    p = tmp_path / "bad.csv"
    p.write_text("Site,IP,Vendor\n../../tmp,10.0.0.1,huawei\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid Site"):
        load_devices_csv(p)
