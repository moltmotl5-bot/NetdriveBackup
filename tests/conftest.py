from __future__ import annotations

import os
from pathlib import Path

import pytest

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
PRIVATE_TESTDATA = Path(os.environ.get("NCCM_PRIVATE_TESTDATA", str(ROOT / "testdata")))


@pytest.fixture(autouse=True)
def _agent_hmac_secret(monkeypatch: pytest.MonkeyPatch):
    if not os.environ.get("NCCM_AGENT_HMAC_SECRET"):
        monkeypatch.setenv("NCCM_AGENT_HMAC_SECRET", "pytest-hmac-secret")


def read_fixture(*parts: str) -> str:
    """Load a committed desensitized CLI sample under tests/fixtures/."""
    return FIXTURES.joinpath(*parts).read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def private_testdata() -> Path:
    return PRIVATE_TESTDATA


@pytest.fixture
def fixture_text():
    return read_fixture
