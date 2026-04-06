"""Tests for search_sessions tool."""

from __future__ import annotations

import asyncio

from aos_cc_mcp.middleware import get_tool_tier
from aos_cc_mcp.modes import Tier
from aos_cc_mcp.tools import search_sessions


class TestSearchSessionsHappyPath:
    def test_search_finds_matches(self) -> None:
        # "git" should appear in most sessions
        result = search_sessions(query="git")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_match_fields_present(self) -> None:
        result = search_sessions(query="git")
        if result:
            m = result[0]
            assert "session_id" in m
            assert "match_count" in m
            assert "first_match_event_index" in m
            assert "first_match_excerpt" in m
            assert "first_match_event_type" in m

    def test_results_sorted_by_match_count(self) -> None:
        result = search_sessions(query="git")
        if len(result) >= 2:
            assert result[0]["match_count"] >= result[1]["match_count"]

    def test_no_matches_returns_empty(self) -> None:
        result = search_sessions(query="xyzzy_absolutely_no_match_999")
        assert result == []


class TestSearchSessionsHardCap:
    def test_hard_cap_50(self) -> None:
        result = search_sessions(query="the", limit=999)
        assert len(result) <= 50

    def test_limit_respected(self) -> None:
        result = search_sessions(query="the", limit=1)
        assert len(result) <= 1


class TestSearchSessionsCaseInsensitive:
    def test_case_insensitive(self) -> None:
        upper = search_sessions(query="GIT")
        lower = search_sessions(query="git")
        # Should find similar results
        upper_ids = {m["session_id"] for m in upper}
        lower_ids = {m["session_id"] for m in lower}
        assert upper_ids == lower_ids


class TestSearchSessionsTierRegistration:
    def test_registered_at_tier_0(self) -> None:
        assert get_tool_tier("search_sessions") == Tier.T0

    def test_callable_through_server(self) -> None:
        from aos_cc_mcp.server import mcp
        result = asyncio.run(mcp.call_tool("search_sessions", {"query": "test"}))
        assert result is not None
