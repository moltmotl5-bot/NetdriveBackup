#!/usr/bin/env python3
"""Ad-hoc: README/Handbook/spec mention per-vendor backup split."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
readme = (ROOT / "README.md").read_text(encoding="utf-8")
handbook = (ROOT / "docs/Handbook.html").read_text(encoding="utf-8")
spec = (ROOT / "docs/NCCM-v3-spec.md").read_text(encoding="utf-8")
for needle, blob, name in [
    ("各廠牌 NetDriver 備份邏輯", readme, "README"),
    ("huawei_backup_commands", readme, "README"),
    ("Unsupported mode: login", handbook, "Handbook"),
    ("Backup by vendor", spec, "NCCM-v3-spec"),
    ("cisco_backup_commands", spec, "NCCM-v3-spec"),
]:
    assert needle in blob, f"{name} missing: {needle}"
print("=== ad-hoc doc-per-vendor-backup verify PASSED ===")