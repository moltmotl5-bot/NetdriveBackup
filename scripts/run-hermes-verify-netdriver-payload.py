#!/usr/bin/env python3
"""Ad-hoc: NCCM NetDriver /api/v1/cmd payload uses login (not enable mode)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nccm.models import NetDriverProfile
from nccm.netdriver.client import NetDriverClient
from nccm.profiles import backup_commands


def main() -> int:
    profile = NetDriverProfile("cisco", "catalyst", "17.0")
    specs = backup_commands("cisco", "catalyst")
    config = next(s for s in specs if s.artifact == "config")
    assert config.command == "show running-config view full", config.command
    assert config.login == "login", config.login
    for s in backup_commands("cisco", "nexus") + backup_commands("cisco", "catalyst"):
        assert s.login == "login", (s.artifact, s.login)

    from nccm.backup.runner import _enable_password_for_vendor

    assert _enable_password_for_vendor("cisco", "secret") == ""
    assert _enable_password_for_vendor("fortinet", "secret") == "secret"
    from nccm.profiles import cisco_running_config_command

    assert cisco_running_config_command("nexus") == "show running-config"
    assert cisco_running_config_command("catalyst") == "show running-config view full"
    nexus_specs = backup_commands("cisco", "nexus")
    nexus_cfg = next(s for s in nexus_specs if s.artifact == "config")
    assert nexus_cfg.command == "show running-config"

    captured: dict = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["body"] = json

        class R:
            status_code = 200

            def json(self):
                return {"code": "OK", "output": "ok"}

        return R()

    client = NetDriverClient(base_url="http://127.0.0.1:8000")
    with patch("nccm.netdriver.client.httpx.post", side_effect=fake_post):
        client.cmd(
            ip="10.0.0.1",
            port=22,
            username="u",
            password="p",
            profile=profile,
            command=config.command,
            login=config.login,
        )

    body = captured["body"]
    cmd0 = body["commands"][0]
    assert "mode" not in cmd0, cmd0
    assert cmd0.get("login") == "login", cmd0
    assert cmd0.get("command") == "show running-config view full", cmd0

    # Agent model accepts legacy "mode" alias when package is on PYTHONPATH
    agent_src = ROOT / "netdrive-agent" / "packages" / "agent" / "src"
    if agent_src.is_dir():
        try:
            sys.path.insert(0, str(agent_src))
            from netdriver_agent.models.cmd import Command

            c_legacy = Command.model_validate(
                {"type": "raw", "mode": "login", "command": "show version", "detail_output": True}
            )
            assert c_legacy.login == "login"
        except ImportError:
            print("agent model skip (deps not installed in verify venv)")

    print(json.dumps({"login": cmd0["login"], "command": cmd0["command"]}, ensure_ascii=False))
    print("=== ad-hoc netdriver-payload verify PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())