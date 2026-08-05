"""Make src/garnish.py importable from the tests."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture(autouse=True)
def _no_ambient_provenance(monkeypatch):
    """Strip the Actions provenance vars CI injects so tests stay deterministic."""
    for var in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_SERVER_URL", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(var, raising=False)
