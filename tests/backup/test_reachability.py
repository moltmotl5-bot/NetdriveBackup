from __future__ import annotations

from nccm.backup.reachability import probe_device
from nccm.models import DeviceRow


def test_probe_device_ok(monkeypatch):
    def fake_probe(self, *, ip, port=22, timeout=3.0):
        return {"ok": True, "latency_ms": 12, "msg": ""}

    monkeypatch.setattr("nccm.netdriver.client.NetDriverClient.probe", fake_probe)
    r = probe_device(DeviceRow(site="s", ip="10.0.0.1", vendor="cisco", port=22))
    assert r.ok is True
    assert r.latency_ms == 12


def test_probe_device_fail(monkeypatch):
    def fake_probe(self, *, ip, port=22, timeout=3.0):
        return {"ok": False, "latency_ms": 0, "msg": "connection refused"}

    monkeypatch.setattr("nccm.netdriver.client.NetDriverClient.probe", fake_probe)
    r = probe_device(DeviceRow(site="s", ip="10.0.0.9", vendor="cisco", port=22))
    assert r.ok is False
    assert "refused" in r.error
