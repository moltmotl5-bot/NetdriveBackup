from __future__ import annotations

from pathlib import Path


def test_compose_agent_not_published_to_host():
    compose = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    lines = compose.read_text(encoding="utf-8").splitlines()
    for line in lines:
        stripped = line.strip()
        if ":8000" in stripped and stripped.startswith("- "):
            assert stripped in ('- "8000"', "- '8000'") or "expose" in stripped
            assert "NETDRIVER_AGENT_PORT" not in stripped
            assert "127.0.0.1" not in stripped or "expose" in stripped
    assert any(line.strip().startswith("expose:") for line in lines)
