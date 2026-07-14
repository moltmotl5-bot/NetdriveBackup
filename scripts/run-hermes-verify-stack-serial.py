#!/usr/bin/env python3
"""Ad-hoc: stack serial_summary must not be IOS-XE SW version string."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
TMPDIR = os.environ.get("TMPDIR") or "/var/folders/py/4zk0t78n2x5bp2br3yfq9l440000gn/T"

INNER = r"""
import sys
ROOT = %r
sys.path.insert(0, ROOT)
from nccm.parsers.stack import parse_cisco_stack_units

iosxe = '''
Switch#   Ports    Model              SW Version        Serial No
*1       58       WS-C3850-48P-L     16.12.05          FCW2147L0B3
 2       58       WS-C3850-48P-L     16.12.05          FCW2147L0B2
'''
units = parse_cisco_stack_units(iosxe)
assert len(units) >= 2, len(units)
for u in units:
    assert u.serial.startswith("FCW"), (u.switch_num, u.serial, u.sw_version)
    assert u.sw_version == "16.12.05", (u.switch_num, u.sw_version)
    assert "16.12" not in u.serial
print("iosxe stack serial vs sw_version: OK")

classic_ios = '''
Switch#   Ports    Model              SW Version        Serial No
*1       32       WS-C3750X-24P-L     15.2(7)E10        FDO1234X5YZ
 2       32       WS-C3750X-24P-L     15.2(7)E10        FDO5678X5YZ
'''
u3 = parse_cisco_stack_units(classic_ios)
assert len(u3) >= 2, len(u3)
for u in u3:
    assert u.serial.startswith("FDO"), (u.switch_num, u.serial, u.sw_version)
    assert u.sw_version == "15.2(7)E10", (u.switch_num, u.sw_version)
    assert "(" not in u.serial
print("classic IOS stack serial vs 15.2(7)E10: OK")

legacy = '''
*1       56       WS-C3850-48P-L       FCW1111ABCD  V02
 2       56       WS-C3850-48P-L       FCW2222ABCD  V02
'''
u2 = parse_cisco_stack_units(legacy)
assert len(u2) >= 2
assert all(u.serial.startswith("FCW") for u in u2)
print("legacy stack serial: OK")
print("=== ad-hoc stack serial verify PASSED ===")
""" % ROOT

fd, path = tempfile.mkstemp(suffix=".py", prefix="hermes-verify-", dir=TMPDIR)
try:
    with os.fdopen(fd, "w") as f:
        f.write(INNER)
    print("created:", path)
    proc = subprocess.run([PY, path], cwd=ROOT, capture_output=True, text=True)
    print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    sys.exit(proc.returncode)
finally:
    try:
        os.unlink(path)
        print("cleaned:", path)
    except OSError:
        pass