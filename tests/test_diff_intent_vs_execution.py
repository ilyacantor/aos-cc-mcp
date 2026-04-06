"""Tests for diff_intent_vs_execution tool."""

from __future__ import annotations

import asyncio

from pathlib import Path

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
            "commits_made", "extraction_mode", "confidence",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_extraction_mode_present(self) -> None:
        result = diff_intent_vs_execution("test-medium")
        assert result["extraction_mode"] in ("git_ls_files", "filename_regex_fallback")

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


class TestDiffIntentLookupApproach:
    """Fix 6: git ls-files lookup and project_dir decoding."""

    def test_decode_project_dir_valid(self) -> None:
        from aos_cc_mcp.tools import _decode_project_dir
        # The test fixtures dir won't match a real filesystem path,
        # so test the decoding logic directly
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            # Create a dir structure that matches the decoded name
            encoded = "-" + td[1:].replace("/", "-")
            result = _decode_project_dir(encoded)
            assert result is not None
            assert str(result) == td

    def test_decode_project_dir_nonexistent(self) -> None:
        from aos_cc_mcp.tools import _decode_project_dir
        result = _decode_project_dir("-nonexistent-path-xyz")
        assert result is None

    def test_decode_project_dir_empty(self) -> None:
        from aos_cc_mcp.tools import _decode_project_dir
        assert _decode_project_dir("") is None
        assert _decode_project_dir("no-leading-dash") is None

    def test_extract_mentions_via_lookup(self) -> None:
        from aos_cc_mcp.tools import _extract_mentions_via_lookup
        tracked = {"src/tools.py", "tests/test_tools.py", "README.md"}
        prompt = "Fix the bug in tools.py and update README.md"
        mentions = _extract_mentions_via_lookup(prompt, tracked)
        basenames = {Path(m).name for m in mentions}
        assert "tools.py" in basenames
        assert "README.md" in basenames

    def test_extract_mentions_no_english_words(self) -> None:
        """Fix 6: English words must not match against the lookup set."""
        from aos_cc_mcp.tools import _extract_mentions_via_lookup
        tracked = {"src/server.py", "tests/test_main.py"}
        prompt = "Fix the topology by specifying realistic synthetic fabric planes"
        mentions = _extract_mentions_via_lookup(prompt, tracked)
        assert mentions == []

    def test_fallback_regex_no_camelcase(self) -> None:
        """Fix 6: fallback regex must not match CamelCase or snake_case words."""
        from aos_cc_mcp.tools import _FILE_EXT_PATTERN
        # Should match file paths
        assert _FILE_EXT_PATTERN.search("fix tools.py")
        assert _FILE_EXT_PATTERN.search("update manifest_intake.py")
        # Should NOT match plain words
        assert not _FILE_EXT_PATTERN.search("SnapshotMeta generates correctly")
        assert not _FILE_EXT_PATTERN.search("source_system and fabric_plane")

    def test_fixture_sessions_use_fallback(self) -> None:
        """Test fixtures have non-resolvable project_dirs, so must use fallback."""
        result = diff_intent_vs_execution("test-medium")
        assert result["extraction_mode"] == "filename_regex_fallback"


class TestDiffIntentTierRegistration:
    def test_registered_at_tier_0(self) -> None:
        assert get_tool_tier("diff_intent_vs_execution") == Tier.T0

    def test_callable_through_server(self) -> None:
        from aos_cc_mcp.server import mcp
        result = asyncio.run(mcp.call_tool("diff_intent_vs_execution", {"session_id": "test-short"}))
        assert result is not None
