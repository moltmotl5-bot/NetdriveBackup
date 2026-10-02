from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from nccm.backup.runner import backup_device
from nccm.models import DeviceRow, NetDriverProfile
from nccm.netdriver.client import NetDriverClient, NetDriverError
from nccm.profiles import backup_commands, cisco_backup_commands
from nccm.storage.writer import write_snapshot


SWITCHMAP_ARTIFACTS = (
    "interfaces_description",
    "ip_interface_brief",
    "vlan_brief",
    "cdp_neighbors",
    "lldp_neighbors",
)

IOS_SWITCHMAP_COMMANDS = {
    "interfaces_description": "show interfaces description",
    "ip_interface_brief": "show ip interface brief",
    "vlan_brief": "show vlan brief",
    "cdp_neighbors": "show cdp neighbors detail",
    "lldp_neighbors": "show lldp neighbors detail",
}

NEXUS_INTERFACES_DESCRIPTION = "show interface description"


def test_cisco_ios_backup_includes_switchmap_commands():
    arts = {s.artifact: s.command for s in cisco_backup_commands("catalyst")}
    assert arts["interfaces"] == "show interface status"
    for name in SWITCHMAP_ARTIFACTS:
        assert name in arts
        assert arts[name] == IOS_SWITCHMAP_COMMANDS[name]
    assert "cdp" not in arts
    assert "lldp" not in arts


def test_cisco_nexus_backup_includes_switchmap_neighbors():
    arts = {s.artifact: s.command for s in cisco_backup_commands("nexus")}
    for name in SWITCHMAP_ARTIFACTS:
        assert name in arts
    assert arts["interfaces_description"] == NEXUS_INTERFACES_DESCRIPTION
    assert (
        arts["interfaces_description"]
        != IOS_SWITCHMAP_COMMANDS["interfaces_description"]
    )
    for name in SWITCHMAP_ARTIFACTS:
        if name == "interfaces_description":
            continue
        assert arts[name] == IOS_SWITCHMAP_COMMANDS[name]
    assert "stack_info" not in [s.artifact for s in cisco_backup_commands("nexus")]


def test_write_snapshot_switchmap_artifact_paths(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NCCM_STORE_DIR", str(tmp_path))
    artifacts = {
        "version_info": "Cisco IOS",
        "config": "hostname lab-sw",
        **{a: f"# mock {a}\nline1\n" for a in SWITCHMAP_ARTIFACTS},
    }
    snap = write_snapshot(
        run_id="run-1",
        site="LAB",
        ip="10.0.0.1",
        hostname="lab-sw",
        vendor="cisco",
        netdriver={"vendor": "cisco", "model": "catalyst", "version": "17.0"},
        artifacts=artifacts,
        status="ok",
    )
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    names = {a["name"] for a in manifest["artifacts"]}
    for name in SWITCHMAP_ARTIFACTS:
        assert (snap / f"{name}.txt").is_file()
        assert name in names


def test_backup_soft_skips_switchmap_command_failures(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("NCCM_STORE_DIR", str(tmp_path))
    monkeypatch.setenv("NCCM_NETDRIVER_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("NCCM_AGENT_HMAC_SECRET", "test-hmac-secret")

    row = DeviceRow(
        site="LAB",
        ip="10.0.0.5",
        port=22,
        vendor="cisco",
        model="catalyst",
        hostname_hint="lab-sw",
    )
    cmds = backup_commands("cisco", "catalyst")

    def fake_cmd(**kwargs):
        command = kwargs["command"]
        if command == "show vlan brief":
            raise NetDriverError("timeout")
        return f"output-for:{command}\n"

    client = NetDriverClient(base_url="http://127.0.0.1:8000")

    with patch.object(client, "cmd", side_effect=fake_cmd):
        with patch(
            "nccm.backup.runner._resolve_profile",
            return_value=(
                NetDriverProfile("cisco", "catalyst", "17.0"),
                "csv",
                "hostname lab-sw\nCisco IOS",
            ),
        ):
            with patch.object(client, "disconnect"):
                with patch("nccm.storage.index_db.index_manifest"):
                    result = backup_device(
                        client,
                        row,
                        run_id="run-soft",
                        username="u",
                        password="p",
                    )

    assert result.status == "ok"
    from pathlib import Path

    snap = Path(result.snapshot_dir)
    assert (snap / "vlan_brief.txt").read_text(encoding="utf-8") == ""
    assert (snap / "cdp_neighbors.txt").read_text(encoding="utf-8").startswith(
        "output-for:show cdp neighbors detail"
    )
    assert len(cmds) == 9
