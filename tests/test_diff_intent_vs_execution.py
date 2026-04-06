"""Tests for diff_intent_vs_execution tool."""

from __future__ import annotations

import asyncio

from aos_cc_mcp.middleware import get_tool_tier
from aos_cc_mcp.modes import Tier
from aos_cc_mcp.tools import diff_intent_vs_execution


class TestDiffIntentHappyPath:
    def test_real_fixture_returns_dict(self) -> None:
        result = diff_intent_vs_execution("test-medium")
        assert isinstance(result, dict)
        assert result["session_id"] == "test-medium"
        assert result["confidence"] == "heuristic"

    def test_result_fields_present(self) -> None:
        result = diff_intent_vs_execution("test-medium")
        for key in [
            "session_id", "first_prompt", "files_mentioned_in_prompt",
            "files_actually_touched", "files_in_prompt_not_touched",
            "files_touched_not_in_prompt", "bash_commands_run",
            "commits_made", "confidence",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_files_actually_touched_is_list(self) -> None:
        result = diff_intent_vs_execution("test-medium")
        assert isinstance(result["files_actually_touched"], list)

    def test_bash_commands_run_is_list(self) -> None:
        result = diff_intent_vs_execution("test-medium")
        assert isinstance(result["bash_commands_run"], list)


class TestDiffIntentEdgeCases:
    def test_missing_session(self) -> None:
        result = diff_intent_vs_execution("nonexistent-id")
        assert result["error"] == "session_not_found"

    def test_short_session(self) -> None:
        result = diff_intent_vs_execution("test-short")
        assert isinstance(result, dict)
        assert "first_prompt" in result


class TestDiffIntentTierRegistration:
    def test_registered_at_tier_0(self) -> None:
        assert get_tool_tier("diff_intent_vs_execution") == Tier.T0

    def test_callable_through_server(self) -> None:
        from aos_cc_mcp.server import mcp
        result = asyncio.run(mcp.call_tool("diff_intent_vs_execution", {"session_id": "test-short"}))
        assert result is not None
