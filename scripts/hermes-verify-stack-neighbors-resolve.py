#!/usr/bin/env python3
"""Ad-hoc: resolve_neighbor_context maps stack display key to logical store dir name."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from nccm.storage.index_db import InventoryDisplayRow, InventoryRow


class TestStackNeighborResolve(unittest.TestCase):
    @patch("nccm.inventory.neighbors.list_inventory_display")
    @patch("nccm.inventory.neighbors.list_inventory")
    def test_stack_display_key_uses_logical_store_hostname(self, mock_li, mock_lid):
        from nccm.inventory.neighbors import resolve_neighbor_context

        mock_li.return_value = [
            InventoryRow(
                device_id="MUSEA::10.0.0.1::22::DS-SW-CEN-2A",
                site="MUSEA",
                ip="10.0.0.1",
                port=22,
                hostname="DS-SW-CEN-2A",
                vendor="Cisco",
                sw_version="",
                model_summary="",
                serial_summary="",
                snapshot_count=1,
                latest_snapshot_id=None,
                latest_snapshot_at=None,
            )
        ]
        display_host = "DS-SW-CEN-2A · SW2"
        mock_lid.return_value = [
            InventoryDisplayRow(
                device_id="MUSEA::10.0.0.1::22::DS-SW-CEN-2A",
                site="MUSEA",
                ip="10.0.0.1",
                port=22,
                hostname=display_host,
                vendor="Cisco",
                sw_version="",
                model_summary="",
                serial_summary="",
                snapshot_count=None,
                stack_switch=2,
                stack_role="Secondary",
                is_config_anchor=False,
                cluster_type="stack",
            )
        ]
        key = f"MUSEA|10.0.0.1|{display_host}"
        _d, logical, store, parse_host, vendor, did = resolve_neighbor_context(key)
        self.assertIsNotNone(logical)
        self.assertEqual(parse_host, display_host)
        self.assertIn("DS-SW-CEN-2A", str(store))
        self.assertNotIn("SW2", str(store).replace("DS-SW-CEN-2A", ""))
        self.assertNotIn("·", str(store))


if __name__ == "__main__":
    unittest.main(verbosity=2)