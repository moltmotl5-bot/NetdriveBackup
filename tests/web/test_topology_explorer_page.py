from __future__ import annotations

from web.main import app
from fastapi.testclient import TestClient


def test_topology_explorer_requires_login():
    client = TestClient(app)
    r = client.get("/neighbors/topology", follow_redirects=False)
    assert r.status_code in (401, 302, 303)
