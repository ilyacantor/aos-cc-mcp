"""Tests for session_summary tool."""

from __future__ import annotations

import asyncio

from aos_cc_mcp.middleware import get_tool_tier
from aos_cc_mcp.modes import Tier
from aos_cc_mcp.tools import session_summary


class TestSessionSummaryHappyPath:
    def test_summary_of_real_fixture(self) -> None:
        result = session_summary("test-medium")
        assert result["session_id"] == "test-medium"
        assert result["user_prompt_count"] >= 1
        assert result["tool_call_count"] >= 1
        assert result["event_count"] > 0
        assert "anomaly_count" in result

    def test_summary_fields_complete(self) -> None:
        result = session_summary("test-short")
        for key in [
            "session_id", "project_dir", "start_time", "end_time",
            "duration_minutes", "user_prompt_count", "tool_call_count",
            "file_edit_count", "bash_command_count", "first_prompt",
            "files_touched", "bash_commands", "anomaly_count",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_files_touched_max_50(self) -> None:
        result = session_summary("test-long")
        assert len(result["files_touched"]) <= 50

    def test_bash_commands_max_50(self) -> None:
        result = session_summary("test-long")
        assert len(result["bash_commands"]) <= 50


class TestSessionSummaryEdgeCases:
    def test_missing_session(self) -> None:
        result = session_summary("nonexistent-session-id")
        assert result["error"] == "session_not_found"

    def test_short_session(self) -> None:
        result = session_summary("test-short")
        assert result["event_count"] > 0


class TestSessionSummaryTierRegistration:
    def test_registered_at_tier_0(self) -> None:
        assert get_tool_tier("session_summary") == Tier.T0

    def test_callable_through_server(self) -> None:
        from aos_cc_mcp.server import mcp
        result = asyncio.run(mcp.call_tool("session_summary", {"session_id": "test-short"}))
        assert result is not None
