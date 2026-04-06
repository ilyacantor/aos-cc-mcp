"""Tests for read_session tool."""

from __future__ import annotations

import asyncio
import json

from aos_cc_mcp.middleware import get_tool_tier
from aos_cc_mcp.modes import Tier
from aos_cc_mcp.tools import read_session


class TestReadSessionSummaryMode:
    def test_summary_delegates(self) -> None:
        result = read_session("test-short", verbosity="summary")
        assert isinstance(result, dict)
        assert "session_id" in result


class TestReadSessionEventsMode:
    def test_events_returns_list(self) -> None:
        result = read_session("test-short", verbosity="events")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_events_have_required_fields(self) -> None:
        result = read_session("test-short", verbosity="events")
        for event in result:
            assert "index" in event
            assert "event_type" in event
            assert "timestamp" in event

    def test_events_no_bodies(self) -> None:
        result = read_session("test-short", verbosity="events")
        for event in result:
            assert "text" not in event
            assert "content" not in event
            assert "before" not in event
            assert "after" not in event


class TestReadSessionFullMode:
    def test_full_returns_list_for_small_session(self) -> None:
        result = read_session("test-short", verbosity="full")
        assert isinstance(result, list)

    def test_full_size_limit(self) -> None:
        result = read_session("test-long", verbosity="full")
        if isinstance(result, dict) and result.get("error") == "size_limit_exceeded":
            assert result["limit"] == 100_000
            assert "suggestion" in result
        else:
            # Small enough to fit
            serialized = json.dumps(result, default=str).encode("utf-8")
            assert len(serialized) <= 100_000


class TestReadSessionEdgeCases:
    def test_missing_session(self) -> None:
        result = read_session("nonexistent-id")
        assert isinstance(result, dict)
        assert result["error"] == "session_not_found"

    def test_invalid_verbosity(self) -> None:
        result = read_session("test-short", verbosity="invalid")
        assert isinstance(result, dict)
        assert result["error"] == "invalid_verbosity"


class TestReadSessionTierRegistration:
    def test_registered_at_tier_0(self) -> None:
        assert get_tool_tier("read_session") == Tier.T0

    def test_callable_through_server(self) -> None:
        from aos_cc_mcp.server import mcp
        result = asyncio.run(mcp.call_tool("read_session", {"session_id": "test-short"}))
        assert result is not None
