from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from nccm.backup.runner import run_backup_job
from nccm.registry.csv import load_devices_csv
from nccm.storage.index_db import rebuild_index


def cmd_backup(args: argparse.Namespace) -> int:
    devices = load_devices_csv(args.csv)
    if not devices:
        print("No devices in CSV", file=sys.stderr)
        return 1

    def log(msg: str) -> None:
        print(msg, flush=True)

    run_id, results = run_backup_job(
        devices,
        username=args.user,
        password=args.password,
        enable_password=args.enable_password,
        log=log,
    )
    ok = sum(1 for r in results if r.status == "ok")
    print(f"run_id={run_id} ok={ok}/{len(results)}")
    for r in results:
        if r.status != "ok":
            print(f"FAIL {r.ip}: {r.error}", file=sys.stderr)
    return 0 if ok == len(results) else 2


def cmd_index_rebuild(_args: argparse.Namespace) -> int:
    d, s = rebuild_index()
    print(f"devices={d} snapshots={s}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description="NCCM v3 CLI")
    sub = p.add_subparsers(dest="command", required=True)

    bp = sub.add_parser("backup", help="Run backup job from CSV")
    bp.add_argument("--csv", required=True, type=Path)
    bp.add_argument("--user", required=True)
    bp.add_argument("--password", required=True)
    bp.add_argument("--enable-password", default="")
    bp.set_defaults(func=cmd_backup)

    ip = sub.add_parser("index", help="Inventory index maintenance")
    ip_sub = ip.add_subparsers(dest="index_cmd", required=True)
    ir = ip_sub.add_parser("rebuild", help="Rescan store/ manifests into index.db")
    ir.set_defaults(func=cmd_index_rebuild)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())