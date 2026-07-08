#!/usr/bin/env python3
"""Ad-hoc NCCM v3 verification (run: PYTHONPATH=. python3 scripts/hermes-verify-nccm-v3.py)."""
from __future__ import annotations

import compileall
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

def _project_root() -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parent, *here.parents]
    for base in candidates:
        if (base / "nccm").is_dir() and (base / "DEMO-v3.csv").is_file():
            return base
    env = os.environ.get("NCCM_APP_ROOT") or os.environ.get("PYTHONPATH", "").split(os.pathsep)[0]
    if env:
        p = Path(env).resolve()
        if (p / "nccm").is_dir():
            return p
    raise RuntimeError("Cannot locate NetdriverBackup project root")


ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


def main() -> int:
    passed: list[str] = []
    failures: list[str] = []

    def ok(msg: str) -> None:
        passed.append(msg)

    def fail(msg: str) -> None:
        failures.append(msg)

    if compileall.compile_dir("nccm", quiet=1):
        ok("compileall nccm")
    else:
        fail("compileall nccm")

    if compileall.compile_dir("web", quiet=1):
        ok("compileall web")
    else:
        fail("compileall web")

    from nccm.registry.csv import load_devices_csv

    rows = load_devices_csv(ROOT / "DEMO-v3.csv")
    if len(rows) == 3:
        ok("DEMO-v3.csv 3 rows")
    else:
        fail(f"DEMO-v3 rows={len(rows)}")
    if sorted(r.port for r in rows) == [18020, 18037, 18038]:
        ok("lab ports")
    else:
        fail("lab ports mismatch")

    wlc = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
    try:
        wlc.write("Site,IP,Vendor\nx,1.1.1.1,cisco_wlc\n")
        wlc.close()
        try:
            load_devices_csv(Path(wlc.name))
            fail("WLC should be rejected")
        except ValueError as e:
            if "WLC" in str(e):
                ok("WLC rejected")
            else:
                fail(f"WLC error: {e}")
    finally:
        Path(wlc.name).unlink(missing_ok=True)

    from nccm.discovery.cisco import classify_cisco_show_version

    if classify_cisco_show_version("NX-OS Nexus").model == "nexus":
        ok("cisco classify nexus")
    else:
        fail("cisco classify")

    from nccm.storage.writer import write_snapshot

    snap = write_snapshot(
        run_id="verify",
        site="lab",
        ip="127.0.0.1",
        port=18020,
        hostname="t",
        vendor="cisco",
        netdriver={"vendor": "cisco", "model": "nexus", "version": "9", "discovery": "auto"},
        artifacts={"version_info": "x"},
        status="ok",
    )
    if (snap / "manifest.json").is_file():
        ok("manifest write")
    else:
        fail("manifest write")

    from nccm.storage.index_db import index_snapshot_dir, list_inventory, rebuild_index

    try:
        index_snapshot_dir(snap)
        inv = list_inventory(query="127.0.0.1")
        if inv and inv[0].ip == "127.0.0.1":
            ok("index_db list_inventory")
        else:
            fail("index_db list_inventory empty")
    except Exception as exc:
        fail(f"index_db: {exc}")

    tr = ROOT / "store" / "lab" / "127.0.0.1__t"
    if tr.is_dir():
        shutil.rmtree(tr)
        ok("cleanup test store")
    rebuild_index()
    ok("index rebuild after cleanup")

    try:
        from nccm.parsers.cdp_lldp import parse_show_cdp_neighbors

        sample_cdp = (
            "Device-ID Local Intrfce  Hldtme Capability  Platform  Port ID\n"
            "R2        Gig 1/0/1       120    R S I      WS-C3750  Gig 1/0/2\n"
        )
        if parse_show_cdp_neighbors(sample_cdp, "sw1"):
            ok("cdp_lldp parse")
        else:
            fail("cdp_lldp parse")
    except Exception as exc:
        fail(f"cdp_lldp: {exc}")

    try:
        from nccm.parsers.interface_map import build_interface_map_table

        cfg = "interface GigabitEthernet1/0/1\n description test\n switchport mode access\n!"
        df, _note, _p = build_interface_map_table(cfg, "", "cisco")
        if df is not None and len(df) >= 1:
            ok("interface_map parse")
        else:
            fail("interface_map parse")
    except Exception as exc:
        fail(f"interface_map: {exc}")

    try:
        from nccm.backup.job_manager import BackupJob

        j = BackupJob(job_id="verify", status="running")
        j.append_log("line1")
        lines, st, pl = j.snapshot(0)
        if lines == ["line1"] and pl is None:
            ok("job_manager snapshot")
        else:
            fail("job_manager snapshot")
    except Exception as exc:
        fail(f"job_manager: {exc}")

    try:
        from web.main import app, NAV

        if len(NAV) == 4:
            ok("nav count 4")
        else:
            fail("nav count")
        paths = {getattr(r, "path", None) for r in app.routes}
        for need in (
            "/backup",
            "/backup/start",
            "/inventory",
            "/inventory/rebuild",
            "/inventory/partial/table",
            "/neighbors",
            "/interfaces",
            "/neighbors/partial/table",
            "/neighbors/partial/detail",
            "/interfaces/partial/detail",
            "/login",
            "/health",
        ):
            if need in paths:
                ok(f"route {need}")
            else:
                fail(f"route {need}")
        if any(p and str(p).startswith("/backup/events") for p in paths):
            ok("route /backup/events/{job_id}")
        else:
            fail("route backup events")
    except Exception as exc:
        fail(f"web.main: {exc}")

    for mod in ("fastapi", "httpx", "jinja2", "uvicorn", "itsdangerous", "pandas"):
        if importlib.util.find_spec(mod):
            ok(f"dep {mod}")
        else:
            fail(f"missing dep {mod}")

    for rel in (
        "docker-compose.yml",
        "docker/Dockerfile.portal",
        "deploy/config/agent/agent.yml",
        "README.md",
    ):
        if (ROOT / rel).is_file():
            ok(f"deploy file {rel}")
        else:
            fail(f"missing {rel}")

    try:
        from nccm.parsers.stack import parse_cisco_stack_units
        from nccm.storage.index_db import device_id

        did = device_id("lab", "10.0.0.1", 22, "Core-Stack")
        if did == "lab::10.0.0.1::22::Core-Stack":
            ok("device_id hostname disambiguation")
        else:
            fail(f"device_id got {did}")
        sample = """
Switch/Stack Mac Address : 0011.2233.4455
*1       Active      0011.2233.4455  15       V01     Ready
 2       Standby     0011.2233.4466  14       V01     Ready
Switch 01
---------
System Serial Number            : FDO1111
Model Number                    : WS-C3750X-24P-L
Switch 02
---------
System Serial Number            : FDO2222
Model Number                    : WS-C3750X-24P-L
"""
        units = parse_cisco_stack_units(sample)
        if len(units) >= 2 and any(u.role.lower() == "active" for u in units):
            ok("cisco stack member parse")
        else:
            fail("cisco stack member parse")
    except Exception as exc:
        fail(f"stack: {exc}")

    print(json.dumps({"pass": passed, "fail": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())