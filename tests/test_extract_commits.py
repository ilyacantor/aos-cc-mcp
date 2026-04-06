"""Tests for extract_commits tool."""

from __future__ import annotations

import asyncio
from pathlib import Path

from aos_cc_mcp.middleware import get_tool_tier
from aos_cc_mcp.modes import Tier
from aos_cc_mcp.parser import parse_session
from aos_cc_mcp.tools import extract_commits, _extract_commits_from_events


ANOMALY_DIR = Path(__file__).parent / "fixtures" / "anomalies"


class TestExtractCommitsHappyPath:
    def test_finds_commits_in_hook_fixture(self) -> None:
        events = parse_session(ANOMALY_DIR / "hook_fire_silent_fix.jsonl")
        commits = _extract_commits_from_events(events, "hook-test")
        assert len(commits) >= 2  # failed commit + successful commit
        # The successful commit (second one) should have parsed hash and message
        successful = [c for c in commits if c["commit_hash"] is not None]
        assert len(successful) >= 1
        c = successful[0]
        assert c["session_id"] == "hook-test"
        assert c["commit_hash"] == "abc1234"
        assert c["message"] is not None

    def test_commit_fields_present(self) -> None:
        events = parse_session(ANOMALY_DIR / "hook_fire_silent_fix.jsonl")
        commits = _extract_commits_from_events(events, "test")
        if commits:
            for key in ["session_id", "timestamp", "commit_hash", "repo", "message", "files_changed"]:
                assert key in commits[0]


class TestExtractCommitsInputValidation:
    def test_requires_exactly_one_mode(self) -> None:
        result = extract_commits(session_id="x", after="2026-01-01", before="2026-12-31")
        assert isinstance(result, dict)
        assert "error" in result

    def test_requires_both_after_and_before(self) -> None:
        result = extract_commits(after="2026-01-01")
        assert isinstance(result, dict)
        assert "error" in result

    def test_missing_session(self) -> None:
        result = extract_commits(session_id="nonexistent-id")
        assert isinstance(result, dict)
        assert result["error"] == "session_not_found"


class TestExtractCommitsNoCommits:
    def test_session_with_no_commits(self) -> None:
        events = parse_session(ANOMALY_DIR / "clean_session.jsonl")
        commits = _extract_commits_from_events(events, "clean")
        assert commits == []


class TestExtractCommitsTierRegistration:
    def test_registered_at_tier_0(self) -> None:
        assert get_tool_tier("extract_commits") == Tier.T0

    def test_callable_through_server(self) -> None:
        from aos_cc_mcp.server import mcp
        result = asyncio.run(mcp.call_tool("extract_commits", {"session_id": "test-short"}))
        assert result is not None
