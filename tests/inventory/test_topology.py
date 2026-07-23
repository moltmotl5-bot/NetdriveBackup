from __future__ import annotations

from nccm.inventory.topology import build_topology


def test_build_topology_empty_store(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    import importlib
    import nccm.config as cfg
    import nccm.storage.index_db as idx
    import nccm.inventory.topology as topo

    importlib.reload(cfg)
    importlib.reload(idx)
    importlib.reload(topo)
    g = topo.build_topology()
    assert g["node_count"] == 0
    assert g["edge_count"] == 0
    assert g["nodes"] == []
