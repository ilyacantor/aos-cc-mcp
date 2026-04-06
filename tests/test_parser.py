"""Tests for the JSONL session log parser.

All fixtures are real Claude Code session files copied from ~/.claude/projects/.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from aos_cc_mcp.events import (
    BashOutput,
    Event,
    FileEdit,
    SessionBoundary,
    ToolCall,
    ToolResult,
    Unknown,
    UserPrompt,
)
from aos_cc_mcp.parser import parse_session

FIXTURES_DIR = Path(__file__).parent / "fixtures"

FIXTURE_FILES = sorted(FIXTURES_DIR.glob("*.jsonl"))


def _count_types(events: list[Event]) -> dict[str, int]:
    """Count events by type name."""
    counts: dict[str, int] = {}
    for e in events:
        name = type(e).__name__
        counts[name] = counts.get(name, 0) + 1
    return counts


def _line_count(path: Path) -> int:
    """Count lines in a file."""
    with path.open() as f:
        return sum(1 for _ in f)


# --- Core contract tests ---


class TestParserReadsWithoutException:
    """Parser reads each real fixture file without raising an exception."""

    def test_dcl_short(self) -> None:
        events = parse_session(FIXTURES_DIR / "session_dcl_short.jsonl")
        assert len(events) > 0

    def test_console_medium(self) -> None:
        events = parse_session(FIXTURES_DIR / "session_console_medium.jsonl")
        assert len(events) > 0

    def test_convergence_long(self) -> None:
        events = parse_session(FIXTURES_DIR / "session_convergence_long.jsonl")
        assert len(events) > 0

    def test_farm_medium(self) -> None:
        events = parse_session(FIXTURES_DIR / "session_farm_medium.jsonl")
        assert len(events) > 0


class TestEventCountEqualsLineCount:
    """Event count equals line count for every fixture (no dropped lines, no duplicates)."""

    def test_dcl_short(self) -> None:
        path = FIXTURES_DIR / "session_dcl_short.jsonl"
        events = parse_session(path)
        assert len(events) == _line_count(path)

    def test_console_medium(self) -> None:
        path = FIXTURES_DIR / "session_console_medium.jsonl"
        events = parse_session(path)
        assert len(events) == _line_count(path)

    def test_convergence_long(self) -> None:
        path = FIXTURES_DIR / "session_convergence_long.jsonl"
        events = parse_session(path)
        assert len(events) == _line_count(path)

    def test_farm_medium(self) -> None:
        path = FIXTURES_DIR / "session_farm_medium.jsonl"
        events = parse_session(path)
        assert len(events) == _line_count(path)


class TestEventTypesPresent:
    """For each fixture, parser produces at least one event of each type that fixture contains."""

    def test_dcl_short_has_expected_types(self) -> None:
        events = parse_session(FIXTURES_DIR / "session_dcl_short.jsonl")
        counts = _count_types(events)
        # Short session should at minimum have user prompts and session boundaries
        assert counts.get("UserPrompt", 0) >= 1
        assert counts.get("SessionBoundary", 0) >= 1

    def test_console_medium_has_tool_calls(self) -> None:
        events = parse_session(FIXTURES_DIR / "session_console_medium.jsonl")
        counts = _count_types(events)
        assert counts.get("ToolCall", 0) >= 1 or counts.get("BashOutput", 0) >= 1

    def test_convergence_long_has_variety(self) -> None:
        events = parse_session(FIXTURES_DIR / "session_convergence_long.jsonl")
        counts = _count_types(events)
        type_names = set(counts.keys())
        # Long session should exercise multiple event types
        assert len(type_names) >= 3

    def test_farm_has_user_prompts(self) -> None:
        events = parse_session(FIXTURES_DIR / "session_farm_medium.jsonl")
        counts = _count_types(events)
        assert counts.get("UserPrompt", 0) >= 1


class TestMalformedLineHandling:
    """Parser handles a deliberately malformed line without crashing, producing Unknown."""

    def test_garbage_line(self, tmp_path: Path) -> None:
        # Copy a real fixture and inject a garbage line
        src = FIXTURES_DIR / "session_dcl_short.jsonl"
        dest = tmp_path / "with_garbage.jsonl"
        shutil.copy(src, dest)

        with dest.open("a") as f:
            f.write("\nTHIS IS NOT VALID JSON {{{garbage}}}\n")

        events = parse_session(dest)
        # Should have original events + 1 Unknown for the garbage line
        original_count = _line_count(src)
        # +2: one for the injected newline (empty line) and one for the garbage line
        assert len(events) == original_count + 2

        # The last non-empty event should be Unknown
        garbage_events = [e for e in events if isinstance(e, Unknown) and isinstance(e.raw.get("_parse_error"), str)]
        assert len(garbage_events) >= 1
        assert "THIS IS NOT VALID JSON" in garbage_events[0].raw["_raw_text"]


class TestRawDictPreserved:
    """Parser preserves the raw dict on every event."""

    def test_all_events_have_raw(self) -> None:
        for fixture_path in FIXTURE_FILES:
            events = parse_session(fixture_path)
            for i, event in enumerate(events):
                assert hasattr(event, "raw"), f"Event {i} in {fixture_path.name} missing raw field"
                assert isinstance(event.raw, dict), f"Event {i} in {fixture_path.name} raw is not dict"


class TestEventOrder:
    """Parser emits events in file order."""

    def test_order_matches_file(self) -> None:
        path = FIXTURES_DIR / "session_console_medium.jsonl"
        events = parse_session(path)

        # Read the file line by line and verify each event's raw dict matches
        with path.open() as f:
            lines = f.readlines()

        assert len(events) == len(lines)
        for i, (event, line) in enumerate(zip(events, lines)):
            line = line.strip()
            if not line:
                continue
            try:
                expected_raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            assert event.raw == expected_raw, f"Event {i} raw dict does not match line {i + 1}"
