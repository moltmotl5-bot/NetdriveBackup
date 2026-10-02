from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import nccm.config as cfg


@pytest.fixture
def store_root(tmp_path, monkeypatch):
    monkeypatch.setenv("NCCM_STORE_DIR", str(tmp_path))
    importlib.reload(cfg)
    return tmp_path


def _write_snap(snap: Path) -> None:
    snap.mkdir(parents=True)
    (snap / "config.txt").write_text("hostname LAB-SW\n!\n", encoding="utf-8")
    (snap / "interfaces.txt").write_text("Port Name Status Vlan\nGi1/0/1 desc connected 10\n", encoding="utf-8")
    (snap / "interfaces_description.txt").write_text("Interface Description\nGi1/0/1 desc\n", encoding="utf-8")
    (snap / "ip_interface_brief.txt").write_text("Interface IP-Address OK?\n", encoding="utf-8")
    (snap / "vlan_brief.txt").write_text("VLAN Name Status\n10 DATA active\n", encoding="utf-8")
    (snap / "cdp_neighbors.txt").write_text("Device ID Local Intrfce\n", encoding="utf-8")
    (snap / "lldp_neighbors.txt").write_text("Local Intf Chassis ID\n", encoding="utf-8")


def test_build_switchdraw_log_command_order(store_root: Path) -> None:
    from nccm.switchmap.log_builder import build_switchdraw_log

    snap = store_root / "lab/10.0.0.1__sw/snapshots/2026-09-30T120000Z"
    _write_snap(snap)
    result = build_switchdraw_log(snap)
    assert result.hostname == "LAB-SW"
    assert not result.missing_artifacts
    text = result.log_text
    assert "LAB-SW#show running-config" in text
    idx_cfg = text.index("show running-config")
    idx_vlan = text.index("show vlan brief")
    idx_cdp = text.index("show cdp neighbors detail")
    assert idx_cfg < idx_vlan < idx_cdp


def test_build_switchdraw_log_empty_interfaces_warns(store_root: Path) -> None:
    from nccm.switchmap.log_builder import build_switchdraw_log

    snap = store_root / "lab/10.0.0.3__sw/snapshots/2026-09-30T120000Z"
    snap.mkdir(parents=True)
    (snap / "config.txt").write_text("hostname X\n", encoding="utf-8")
    (snap / "interfaces.txt").write_text("", encoding="utf-8")
    result = build_switchdraw_log(snap)
    assert "interfaces" not in result.missing_artifacts
    assert any("interfaces.txt 為空" in w for w in result.warnings)


def test_build_switchdraw_log_strips_interface_command_echo(store_root: Path) -> None:
    from nccm.switchmap.log_builder import build_switchdraw_log

    snap = store_root / "lab/10.0.0.4__sw/snapshots/2026-09-30T120000Z"
    snap.mkdir(parents=True)
    (snap / "config.txt").write_text("hostname LAB-SW\n!\n", encoding="utf-8")
    (snap / "interfaces.txt").write_text(
        "LAB-SW#show interface status\n\nPort Name Status Vlan\nGi1/0/1 desc connected 10\n",
        encoding="utf-8",
    )
    result = build_switchdraw_log(snap)
    assert "LAB-SW#show interface status" not in result.log_text.split("show interfaces status", 1)[1]


def test_build_switchdraw_log_missing_artifacts(store_root: Path) -> None:
    from nccm.switchmap.log_builder import build_switchdraw_log

    snap = store_root / "lab/10.0.0.2__sw/snapshots/2026-09-30T120000Z"
    snap.mkdir(parents=True)
    (snap / "config.txt").write_text("hostname X\n", encoding="utf-8")
    result = build_switchdraw_log(snap)
    assert "config" not in result.missing_artifacts
    assert "vlan_brief" in result.missing_artifacts
    assert "interfaces" in result.missing_artifacts
    assert any("interfaces.txt" in w for w in result.warnings)
