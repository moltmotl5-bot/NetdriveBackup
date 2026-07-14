#!/usr/bin/env python3
"""Ad-hoc: stack CDP/LLDP detail uses same snapshot as table row."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from nccm.inventory.neighbors import neighbor_device_rows, neighbors_for_device

rows, lookup = neighbor_device_rows()
stack_rows = [r for r in rows if r.get("stack_switch") is not None]
if not stack_rows:
    print("SKIP: no stack rows in index (nothing to assert)")
    sys.exit(0)

r = stack_rows[0]
dk = r["device_key"]
nrows, cdp, lldp, ver = neighbors_for_device(dk, lookup=lookup)
print("device_key:", dk)
print("table: cdp=%s count=%s" % (r["cdp_status"], r["neighbor_count"]))
print("detail: cdp=%s count=%s ver=%s" % (cdp, len(nrows), ver))
if r["cdp_status"] == "ok" and r["neighbor_count"] > 0:
    assert cdp == "ok", "detail cdp should be ok when table is ok"
    assert len(nrows) == r["neighbor_count"], "detail neighbor count mismatch"
print("=== stack neighbors consistency PASSED ===")