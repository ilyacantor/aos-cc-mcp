"""Tests for list_sessions tool."""

from __future__ import annotations

import asyncio
from pathlib import Path

from aos_cc_mcp.middleware import get_tool_tier
from aos_cc_mcp.modes import Tier
from aos_cc_mcp.tools import list_sessions


class TestListSessionsHappyPath:
    def test_returns_sessions_from_fixtures(self) -> None:
        result = list_sessions()
        assert isinstance(result, list)
        assert len(result) > 0

    def test_session_metadata_fields(self) -> None:
        result = list_sessions()
        session = result[0]
        assert "session_id" in session
        assert "project_dir" in session
        assert "file_bytes" in session
        assert isinstance(session["file_bytes"], int)

    def test_project_filter(self) -> None:
        result = list_sessions(project_filter="-test-project")
        assert len(result) > 0
        for s in result:
            assert "-test-project" in s["project_dir"]

    def test_project_filter_no_match(self) -> None:
        result = list_sessions(project_filter="nonexistent-project-xyz")
        assert result == []


class TestListSessionsHardCap:
    def test_limit_respected(self) -> None:
        result = list_sessions(limit=1)
        assert len(result) <= 1

    def test_hard_cap_200(self) -> None:
        result = list_sessions(limit=999)
        assert len(result) <= 200


class TestListSessionsTierRegistration:
    def test_registered_at_tier_0(self) -> None:
        tier = get_tool_tier("list_sessions")
        assert tier == Tier.T0

    def test_callable_through_server(self) -> None:
        from aos_cc_mcp.server import mcp
        result = asyncio.run(mcp.call_tool("list_sessions", {"limit": 5}))
        assert result is not None
