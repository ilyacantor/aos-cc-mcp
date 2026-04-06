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


class TestReadSessionToolUseId:
    """Fix 9: ToolCall and ToolResult events include tool_use_id at events verbosity."""

    def test_tool_call_has_tool_use_id_field(self) -> None:
        result = read_session("test-short", verbosity="events")
        tool_calls = [e for e in result if e["event_type"] == "ToolCall"]
        if tool_calls:
            assert "tool_use_id" in tool_calls[0]

    def test_tool_result_has_tool_use_id_field(self) -> None:
        result = read_session("test-short", verbosity="events")
        tool_results = [e for e in result if e["event_type"] == "ToolResult"]
        if tool_results:
            assert "tool_use_id" in tool_results[0]

    def test_bash_output_has_tool_use_id_field(self) -> None:
        result = read_session("test-short", verbosity="events")
        bash_events = [e for e in result if e["event_type"] == "BashOutput"]
        if bash_events:
            assert "tool_use_id" in bash_events[0]


class TestReadSessionUnknownSubtype:
    """Fix 9: Unknown events include a subtype field at events verbosity."""

    def test_unknown_events_have_subtype(self) -> None:
        result = read_session("test-medium", verbosity="events")
        unknowns = [e for e in result if e["event_type"] == "Unknown"]
        for u in unknowns:
            assert "subtype" in u
            assert u["subtype"] in (
                "assistant_text", "assistant_thinking", "harness_internal",
                "attachment_delta", "other",
            )

    def test_assistant_text_subtype(self) -> None:
        """Assistant text blocks should get subtype 'assistant_text'."""
        from aos_cc_mcp.events import Unknown
        from aos_cc_mcp.tools import _classify_unknown_subtype
        event = Unknown(
            timestamp="2026-01-01T00:00:00Z",
            raw={"type": "assistant", "message": {"content": [{"type": "text", "text": "hello"}]}},
        )
        assert _classify_unknown_subtype(event) == "assistant_text"

    def test_assistant_thinking_subtype(self) -> None:
        from aos_cc_mcp.events import Unknown
        from aos_cc_mcp.tools import _classify_unknown_subtype
        event = Unknown(
            timestamp="2026-01-01T00:00:00Z",
            raw={"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "..."}]}},
        )
        assert _classify_unknown_subtype(event) == "assistant_thinking"

    def test_harness_internal_subtype(self) -> None:
        from aos_cc_mcp.events import Unknown
        from aos_cc_mcp.tools import _classify_unknown_subtype
        for event_type in ("custom-title", "agent-name", "queue-operation"):
            event = Unknown(timestamp=None, raw={"type": event_type})
            assert _classify_unknown_subtype(event) == "harness_internal"

    def test_attachment_delta_subtype(self) -> None:
        from aos_cc_mcp.events import Unknown
        from aos_cc_mcp.tools import _classify_unknown_subtype
        event = Unknown(timestamp=None, raw={"type": "attachment", "attachment": {"some": "data"}})
        assert _classify_unknown_subtype(event) == "attachment_delta"

    def test_other_subtype(self) -> None:
        from aos_cc_mcp.events import Unknown
        from aos_cc_mcp.tools import _classify_unknown_subtype
        event = Unknown(timestamp=None, raw={"type": "something_new"})
        assert _classify_unknown_subtype(event) == "other"


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
