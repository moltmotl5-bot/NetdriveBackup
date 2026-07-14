#!/usr/bin/env python3
"""Ad-hoc: UI copy + README/Handbook alignment (sidebar, backup vendors, config warn)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMPDIR = os.environ.get("TMPDIR") or "/var/folders/py/4zk0t78n2x5bp2br3yfq9l440000gn/T"

INNER = r"""
import pathlib
import sys

ROOT = %r
base = (pathlib.Path(ROOT) / "web/templates/base.html").read_text(encoding="utf-8")
backup = (pathlib.Path(ROOT) / "web/templates/backup.html").read_text(encoding="utf-8")
detail = (pathlib.Path(ROOT) / "web/templates/partials/inventory_detail.html").read_text(encoding="utf-8")
readme = (pathlib.Path(ROOT) / "README.md").read_text(encoding="utf-8")
handbook = (pathlib.Path(ROOT) / "docs/Handbook.html").read_text(encoding="utf-8")
css = (pathlib.Path(ROOT) / "web/static/nccm.css").read_text(encoding="utf-8")

assert "sidebar-user-row" in base
assert "position: fixed" in css
assert "margin-left: 240px" in css
assert 'class="logout"' in base
assert "{{ agent_url }}" not in base
assert "store: {{ store }}" not in base
assert "Online" in (pathlib.Path(ROOT) / "web/main.py").read_text(encoding="utf-8")
assert "Cisco@123" not in backup
assert "支援廠牌" in backup
assert "還原" in detail
assert "開發自檢" not in readme
assert "Online" in readme and "Offline" in readme
assert "支援廠牌" in handbook
assert "hermes-verify-nccm-v3" not in handbook
print("ui copy + docs: OK")
print("=== ad-hoc ui-doc verify PASSED ===")
""" % ROOT

fd, path = tempfile.mkstemp(suffix=".py", prefix="hermes-verify-", dir=TMPDIR)
try:
    with os.fdopen(fd, "w") as f:
        f.write(INNER)
    print("created:", path)
    proc = subprocess.run([sys.executable, path], cwd=ROOT, capture_output=True, text=True)
    print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    if proc.returncode:
        sys.exit(proc.returncode)
finally:
    try:
        os.unlink(path)
        print("cleaned:", path)
    except OSError as e:
        print("cleanup note:", e)