"""Shared test configuration and fixtures for tool tests."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
ANOMALY_FIXTURES = FIXTURES_DIR / "anomalies"
PROJECT_FIXTURES = FIXTURES_DIR / "-test-project"


@pytest.fixture(autouse=True)
def _patch_sessions_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point SESSIONS_BASE at the test fixtures directory so tools can discover sessions."""
    import aos_cc_mcp.tools as tools_mod
    monkeypatch.setattr(tools_mod, "SESSIONS_BASE", FIXTURES_DIR)
