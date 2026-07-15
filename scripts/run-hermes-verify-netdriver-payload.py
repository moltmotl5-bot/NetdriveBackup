#!/usr/bin/env python3
"""Ad-hoc: per-vendor NetDriver /api/v1/cmd command objects."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nccm.models import NetDriverProfile
from nccm.netdriver.client import NetDriverClient
from nccm.profiles import (
    backup_commands,
    cisco_running_config_command,
    default_agent_mode,
    huawei_backup_commands,
    fortinet_backup_commands,
)


def main() -> int:
    assert default_agent_mode("cisco") == "login"
    assert default_agent_mode("huawei") == "enable"
    assert default_agent_mode("fortinet") == "enable"

    ios_cfg = next(s for s in backup_commands("cisco", "catalyst") if s.artifact == "config")
    assert ios_cfg.command == "show running-config view full"
    assert ios_cfg.agent_mode == "login"

    nexus_cfg = next(s for s in backup_commands("cisco", "nexus") if s.artifact == "config")
    assert nexus_cfg.command == "show running-config"
    assert nexus_cfg.agent_mode == "login"

    for s in huawei_backup_commands():
        assert s.agent_mode == "enable", s.artifact
    for s in fortinet_backup_commands():
        assert s.agent_mode == "enable", s.artifact

    assert cisco_running_config_command("nexus") == "show running-config"
    assert cisco_running_config_command("catalyst") == "show running-config view full"

    from nccm.backup.runner import _enable_password_for_vendor

    assert _enable_password_for_vendor("cisco", "secret") == ""
    assert _enable_password_for_vendor("huawei", "secret") == "secret"

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
    assert cmd0.get("mode") == "enable", cmd0
    assert "login" not in cmd0

    print(json.dumps({"huawei_cmd": cmd0}, ensure_ascii=False))
    print("=== ad-hoc netdriver-payload verify PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())