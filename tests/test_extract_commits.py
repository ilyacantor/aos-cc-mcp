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


class TestExtractCommitsDateRange:
    """Fix 1: naive ISO strings in date-range mode must not crash."""

    def test_naive_date_range_no_crash(self) -> None:
        result = extract_commits(after="2020-01-01T00:00:00", before="2099-12-31T23:59:59")
        assert isinstance(result, list)


class TestExtractCommitsRootCommit:
    """Fix 4: root-commit format must be parsed."""

    def test_root_commit_regex(self) -> None:
        from aos_cc_mcp.tools import _COMMIT_HASH_RE
        # Normal format
        m = _COMMIT_HASH_RE.search("[master abc1234] fix lint")
        assert m and m.group(1) == "abc1234"
        # Root-commit format
        m = _COMMIT_HASH_RE.search("[master (root-commit) a2c6d25] Phase 1a")
        assert m and m.group(1) == "a2c6d25"
        # Branch with slashes
        m = _COMMIT_HASH_RE.search("[dev/feature deadbeef] some change")
        assert m and m.group(1) == "deadbeef"


class TestExtractCommitsRepoPath:
    """Fix 5: repo path extraction from cd prefix in bash commands."""

    def test_cd_prefix_extraction(self) -> None:
        from aos_cc_mcp.tools import _extract_repo_from_command
        assert _extract_repo_from_command(
            "cd ~/code/foo && git commit -m 'test'", None
        ) == str(Path.home() / "code" / "foo")

    def test_absolute_cd_prefix(self) -> None:
        from aos_cc_mcp.tools import _extract_repo_from_command
        assert _extract_repo_from_command(
            "cd /absolute/path && git commit -m 'test'", None
        ) == "/absolute/path"

    def test_no_cd_prefix_uses_fallback(self) -> None:
        from aos_cc_mcp.tools import _extract_repo_from_command
        assert _extract_repo_from_command(
            "git commit -m 'test'", "/fallback/dir"
        ) == "/fallback/dir"

    def test_no_cd_no_fallback(self) -> None:
        from aos_cc_mcp.tools import _extract_repo_from_command
        assert _extract_repo_from_command("git commit -m 'test'", None) is None


class TestExtractCommitsTierRegistration:
    def test_registered_at_tier_0(self) -> None:
        assert get_tool_tier("extract_commits") == Tier.T0

    def test_callable_through_server(self) -> None:
        from aos_cc_mcp.server import mcp
        result = asyncio.run(mcp.call_tool("extract_commits", {"session_id": "test-short"}))
        assert result is not None
