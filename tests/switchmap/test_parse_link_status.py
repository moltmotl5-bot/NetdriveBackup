"""Regression: SwitchMap faceplate must not show misleading 'unknown' link status."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PARSE_JS = ROOT / "web/static/switchmap/parse.js"
FACEPLATE_JS = ROOT / "web/static/switchmap/faceplate.js"


def _run_parse(log_text: str) -> list[dict]:
    script = f"""
const fs = require('fs');
const vm = require('vm');
const ctx = {{ SwitchDraw: {{}} }};
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync({json.dumps(str(PARSE_JS))}, 'utf8'), ctx);
vm.runInContext(fs.readFileSync({json.dumps(str(FACEPLATE_JS))}, 'utf8'), ctx);
const SD = ctx.SwitchDraw;
const log = {json.dumps(log_text)};
const devices = SD.parseLog(log);
console.log(JSON.stringify(devices.map(function (d) {{
  return {{
    ports: d.physicalPorts.map(function (p) {{
      return {{
        name: p.name,
        linkStatus: p.linkStatus,
        statusText: SD.portStatusDisplay(p).text
      }};
    }})
  }};
}})));
"""
    out = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(out.stdout)


def test_description_status_without_description_text() -> None:
    """show int desc rows with empty Description still supply link status."""
    log = """SW1#show running-config
interface GigabitEthernet1/0/1
 switchport access vlan 10
!
SW1#show interfaces description
Interface                      Status         Protocol Description
Gi1/0/1                        notconnect     down
"""
    data = _run_parse(log)
    port = data[0]["ports"][0]
    assert port["linkStatus"] == "notconnect"
    assert port["statusText"] == "notconnect"
    assert port["statusText"] != "unknown"


def test_interfaces_status_table_beats_description() -> None:
    """show interfaces status Status column wins over show int desc."""
    log = """SW1#show running-config
interface GigabitEthernet1/0/1
 switchport access vlan 10
!
SW1#show interfaces status
Port      Name               Status       Vlan
Gi1/0/1   UPLINK             connected    10
SW1#show interfaces description
Interface                      Status         Protocol Description
Gi1/0/1                        down           down     stale
"""
    data = _run_parse(log)
    port = data[0]["ports"][0]
    assert port["linkStatus"] == "connected"
    assert port["statusText"] == "connected"


def test_ip_brief_fills_missing_status_table_row() -> None:
    log = """SW1#show running-config
interface GigabitEthernet1/0/1
 switchport access vlan 10
!
SW1#show interfaces status
Port      Name               Status       Vlan
SW1#show ip interface brief
Interface              IP-Address      OK? Method Status                Protocol
Gi1/0/1                unassigned      YES unset  up                    up
"""
    data = _run_parse(log)
    port = data[0]["ports"][0]
    assert port["linkStatus"] == "connected"
    assert port["statusText"] == "connected"


def test_missing_status_shows_em_dash_not_unknown() -> None:
    log = """SW1#show running-config
interface GigabitEthernet1/0/5
 switchport access vlan 10
!
SW1#show interfaces status
Port      Name               Status       Vlan
Gi1/0/1   UPLINK             connected    10
"""
    data = _run_parse(log)
    orphan = next(p for p in data[0]["ports"] if p["name"] == "Gi1/0/5")
    assert orphan["linkStatus"] == ""
    assert orphan["statusText"] == "—"
