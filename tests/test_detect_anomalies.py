"""Tests for detect_anomalies tool — one test per rule, positive and negative."""

from __future__ import annotations

import asyncio
from pathlib import Path

from aos_cc_mcp.anomaly_rules import (
    rule_hook_bypass_attempt,
    rule_hook_fire_with_silent_fix,
    rule_scope_expansion,
    rule_silent_error,
    rule_test_skip_added,
    rule_uncommitted_work_at_session_end,
    rule_verification_returned_empty,
    run_all_rules,
)
from aos_cc_mcp.middleware import get_tool_tier
from aos_cc_mcp.modes import Tier
from aos_cc_mcp.parser import parse_session
from aos_cc_mcp.tools import detect_anomalies

ANOMALY_DIR = Path(__file__).parent / "fixtures" / "anomalies"


def _load(name: str):
    return parse_session(ANOMALY_DIR / name)


# --- Rule 1: hook_fire_with_silent_fix ---

class TestRuleHookFireWithSilentFix:
    def test_positive(self) -> None:
        events = _load("hook_fire_silent_fix.jsonl")
        results = rule_hook_fire_with_silent_fix(events, "test")
        assert len(results) >= 1
        assert results[0]["rule_id"] == "hook_fire_with_silent_fix"

    def test_negative(self) -> None:
        events = _load("clean_session.jsonl")
        results = rule_hook_fire_with_silent_fix(events, "test")
        assert results == []


# --- Rule 2: test_skip_added ---

class TestRuleTestSkipAdded:
    def test_positive(self) -> None:
        events = _load("test_skip_added.jsonl")
        results = rule_test_skip_added(events, "test")
        assert len(results) >= 1
        assert results[0]["rule_id"] == "test_skip_added"
        assert results[0]["details"]["matched_marker"] == "@pytest.mark.skip"

    def test_negative(self) -> None:
        events = _load("clean_session.jsonl")
        results = rule_test_skip_added(events, "test")
        assert results == []


# --- Rule 3: verification_returned_empty ---

class TestRuleVerificationReturnedEmpty:
    def test_positive(self) -> None:
        events = _load("verification_empty.jsonl")
        results = rule_verification_returned_empty(events, "test")
        assert len(results) >= 1
        assert results[0]["rule_id"] == "verification_returned_empty"

    def test_negative(self) -> None:
        events = _load("clean_session.jsonl")
        results = rule_verification_returned_empty(events, "test")
        assert results == []


# --- Rule 4: scope_expansion (reserved) ---

class TestRuleScopeExpansion:
    def test_always_empty(self) -> None:
        events = _load("clean_session.jsonl")
        results = rule_scope_expansion(events, "test")
        assert results == []


# --- Rule 5: silent_error ---

class TestRuleSilentError:
    def test_positive(self) -> None:
        events = _load("silent_error.jsonl")
        results = rule_silent_error(events, "test")
        assert len(results) >= 1
        assert results[0]["rule_id"] == "silent_error"
        assert "ConnectionError" in results[0]["details"]["error"]

    def test_negative(self) -> None:
        events = _load("clean_session.jsonl")
        results = rule_silent_error(events, "test")
        assert results == []


# --- Rule 6: hook_bypass_attempt ---

class TestRuleHookBypassAttempt:
    def test_positive(self) -> None:
        events = _load("hook_bypass.jsonl")
        results = rule_hook_bypass_attempt(events, "test")
        assert len(results) >= 1
        assert results[0]["rule_id"] == "hook_bypass_attempt"
        assert results[0]["details"]["matched_pattern"] == "--no-verify"

    def test_negative(self) -> None:
        events = _load("clean_session.jsonl")
        results = rule_hook_bypass_attempt(events, "test")
        assert results == []


# --- Rule 7: uncommitted_work_at_session_end ---

class TestRuleUncommittedWorkAtSessionEnd:
    def test_positive(self) -> None:
        events = _load("uncommitted_end.jsonl")
        results = rule_uncommitted_work_at_session_end(events, "test")
        assert len(results) >= 1
        assert results[0]["rule_id"] == "uncommitted_work_at_session_end"
        assert len(results[0]["details"]["uncommitted_files"]) >= 1

    def test_negative(self) -> None:
        events = _load("clean_session.jsonl")
        results = rule_uncommitted_work_at_session_end(events, "test")
        assert results == []


# --- Integration tests ---

class TestDetectAnomaliesCleanSession:
    def test_clean_session_zero_anomalies(self) -> None:
        events = _load("clean_session.jsonl")
        results = run_all_rules(events, "clean")
        assert results == []


class TestDetectAnomaliesRealFixture:
    def test_real_fixture_produces_anomalies(self) -> None:
        events = parse_session(Path(__file__).parent / "fixtures" / "session_console_medium.jsonl")
        results = run_all_rules(events, "console-medium")
        assert isinstance(results, list)
        # We know from earlier testing this produces some anomalies


class TestDetectAnomaliesInputValidation:
    def test_requires_exactly_one_mode(self) -> None:
        result = detect_anomalies(session_id="x", after="2026-01-01", before="2026-12-31")
        assert isinstance(result, dict)
        assert "error" in result

    def test_missing_session(self) -> None:
        result = detect_anomalies(session_id="nonexistent-id")
        assert isinstance(result, dict)
        assert result["error"] == "session_not_found"


class TestDetectAnomaliesTierRegistration:
    def test_registered_at_tier_0(self) -> None:
        assert get_tool_tier("detect_anomalies") == Tier.T0

    def test_callable_through_server(self) -> None:
        from aos_cc_mcp.server import mcp
        result = asyncio.run(mcp.call_tool("detect_anomalies", {"session_id": "test-short"}))
        assert result is not None
