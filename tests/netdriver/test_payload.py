from __future__ import annotations

from unittest.mock import patch

from nccm.backup.runner import _enable_password_for_vendor
from nccm.models import NetDriverProfile
from nccm.netdriver.client import NetDriverClient
from nccm.profiles import (
    backup_commands,
    cisco_running_config_command,
    default_agent_mode,
    fortinet_backup_commands,
    huawei_backup_commands,
)


def test_agent_modes_per_vendor():
    assert default_agent_mode("cisco") == "login"
    assert default_agent_mode("huawei") == "enable"
    assert default_agent_mode("fortinet") == "enable"


def test_cisco_config_commands():
    ios_cfg = next(s for s in backup_commands("cisco", "catalyst") if s.artifact == "config")
    assert ios_cfg.command == "show running-config view full"
    assert ios_cfg.agent_mode == "login"
    nexus_cfg = next(s for s in backup_commands("cisco", "nexus") if s.artifact == "config")
    assert nexus_cfg.command == "show running-config"
    assert cisco_running_config_command("nexus") == "show running-config"


def test_huawei_fortinet_enable_mode():
    for s in huawei_backup_commands():
        assert s.agent_mode == "enable", s.artifact
    for s in fortinet_backup_commands():
        assert s.agent_mode == "enable", s.artifact
    assert _enable_password_for_vendor("cisco", "secret") == ""
    assert _enable_password_for_vendor("huawei", "secret") == "secret"


def test_command_entry_shape():
    cisco_entry = NetDriverClient.command_entry(
        vendor="cisco", agent_mode="login", command="show version"
    )
    assert cisco_entry.get("login") == "login"
    assert "mode" not in cisco_entry

    huawei_entry = NetDriverClient.command_entry(
        vendor="huawei", agent_mode="enable", command="display version"
    )
    assert huawei_entry.get("mode") == "enable"
    assert "login" not in huawei_entry


def test_client_cmd_payload_huawei():
    captured: dict = {}

    def fake_post(url, json=None, timeout=None):
        captured["body"] = json

        class R:
            status_code = 200

            def json(self):
                return {"code": "OK", "output": "ok"}

        return R()

    profile = NetDriverProfile("huawei", "ce", "8.0")
    client = NetDriverClient(base_url="http://127.0.0.1:8000")
    with patch("nccm.netdriver.client.httpx.post", side_effect=fake_post):
        client.cmd(
            ip="10.0.0.1",
            port=22,
            username="u",
            password="p",
            profile=profile,
            command="display version",
            agent_mode="enable",
        )
    cmd0 = captured["body"]["commands"][0]
    assert cmd0.get("mode") == "enable"
    assert "login" not in cmd0
