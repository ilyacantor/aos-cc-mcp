"""Mechanical anomaly detection rules for Claude Code session analysis.

Each rule is a pure function: takes a list of events and returns anomaly dicts.
No judgment calls — only structural pattern matching.
"""

from __future__ import annotations

import re
from typing import Any

from .events import (
    BashOutput,
    Event,
    FileEdit,
    SessionBoundary,
    ToolCall,
    ToolResult,
    Unknown,
    UserPrompt,
)


def _get_tool_use_id(event: Event) -> str | None:
    """Extract tool_use_id from an event's raw dict."""
    raw = event.raw
    msg = raw.get("message", {})
    content = msg.get("content", [])
    if not isinstance(content, list):
        return None
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            return block.get("id")
        if block.get("type") == "tool_result":
            return block.get("tool_use_id")
    return None


def _find_correlated_result(events: list[Event], call_index: int) -> tuple[int, ToolResult] | None:
    """Find the ToolResult correlated to a call event by tool_use_id."""
    call_id = _get_tool_use_id(events[call_index])
    if not call_id:
        return None
    for j in range(call_index + 1, min(len(events), call_index + 30)):
        if isinstance(events[j], ToolResult) and _get_tool_use_id(events[j]) == call_id:
            return (j, events[j])
    return None


def _excerpt(event: Event, max_len: int = 200) -> str:
    """Extract a short text excerpt from an event."""
    if isinstance(event, UserPrompt):
        return event.text[:max_len]
    if isinstance(event, BashOutput):
        return event.command[:max_len]
    if isinstance(event, FileEdit):
        return f"{event.file_path}: {event.after[:max_len - len(event.file_path) - 2]}"
    if isinstance(event, ToolResult):
        return event.content[:max_len]
    if isinstance(event, ToolCall):
        return f"{event.tool_name}: {str(event.input_params)[:max_len - len(event.tool_name) - 2]}"
    return ""


# ---------------------------------------------------------------------------
# Rule 1: hook_fire_with_silent_fix
# ---------------------------------------------------------------------------

def rule_hook_fire_with_silent_fix(events: list[Event], session_id: str) -> list[dict[str, Any]]:
    """A pre-commit hook fires (non-zero exit), agent edits files, then commits successfully."""
    anomalies: list[dict[str, Any]] = []

    for i, event in enumerate(events):
        if not isinstance(event, BashOutput):
            continue
        # Check if this is a pre-commit or hook-related command
        cmd = event.command.lower()
        if "pre-commit" not in cmd and ".git/hooks/" not in cmd and "git commit" not in cmd:
            continue

        # Correlate with its ToolResult to check for hook failure
        corr = _find_correlated_result(events, i)
        if corr is None:
            continue
        result_idx, result = corr
        output = result.content.lower()
        if "hook" not in output:
            continue
        # Check for failure: is_error, exit code mention, or known failure patterns
        if result.success and "failed" not in output and "error" not in output:
            continue

        # Look within next 10 events for FileEdits followed by successful git commit
        window = events[i + 1:i + 11]
        edit_indices: list[int] = []
        commit_found = False

        for j, w_event in enumerate(window):
            actual_idx = i + 1 + j
            if isinstance(w_event, FileEdit):
                edit_indices.append(actual_idx)
            if isinstance(w_event, BashOutput) and "git commit" in w_event.command:
                w_corr = _find_correlated_result(events, actual_idx)
                if w_corr and (w_corr[1].success or "failed" not in w_corr[1].content.lower()):
                    commit_found = True
                    break

        if edit_indices and commit_found:
            for edit_idx in edit_indices:
                anomalies.append({
                    "session_id": session_id,
                    "rule_id": "hook_fire_with_silent_fix",
                    "event_index": edit_idx,
                    "timestamp": events[edit_idx].timestamp,
                    "excerpt": _excerpt(events[edit_idx]),
                    "details": {
                        "hook_command_index": i,
                        "commit_index": actual_idx,
                    },
                })

    return anomalies


# ---------------------------------------------------------------------------
# Rule 2: test_skip_added
# ---------------------------------------------------------------------------

_SKIP_MARKERS = [
    "@pytest.mark.skip",
    "@pytest.mark.xfail",
    ".skip(",
    "xit(",
    "test.skip(",
    "describe.skip(",
]


def rule_test_skip_added(events: list[Event], session_id: str) -> list[dict[str, Any]]:
    """A FileEdit whose diff contains test skip/xfail markers."""
    anomalies: list[dict[str, Any]] = []

    for i, event in enumerate(events):
        if not isinstance(event, FileEdit):
            continue
        diff_text = event.after  # The "new" content from the edit
        for marker in _SKIP_MARKERS:
            if marker in diff_text:
                anomalies.append({
                    "session_id": session_id,
                    "rule_id": "test_skip_added",
                    "event_index": i,
                    "timestamp": event.timestamp,
                    "excerpt": _excerpt(event),
                    "details": {"matched_marker": marker, "file_path": event.file_path},
                })
                break  # One anomaly per edit, even if multiple markers match

    return anomalies


# ---------------------------------------------------------------------------
# Rule 3: verification_returned_empty
# ---------------------------------------------------------------------------

_VERIFICATION_PATTERNS = re.compile(
    r"SELECT|count\(|grep |find |rg |ripgrep", re.IGNORECASE
)

_EMPTY_PATTERNS = [
    "",
    "0",
    "0 rows",
    "(0 rows)",
    "no matches found",
    "no results",
    "0 matches",
]


def rule_verification_returned_empty(events: list[Event], session_id: str) -> list[dict[str, Any]]:
    """A verification query returns empty/zero and the agent continues without flagging it."""
    anomalies: list[dict[str, Any]] = []

    for i, event in enumerate(events):
        if not isinstance(event, ToolResult):
            continue

        # Find the correlated call to check if it's a verification command
        call_id = _get_tool_use_id(event)
        if not call_id:
            continue

        # Look backward for the call
        call_event = None
        for j in range(max(0, i - 20), i):
            if _get_tool_use_id(events[j]) == call_id:
                call_event = events[j]
                break

        if call_event is None:
            continue

        # Check if the call is a verification command
        call_text = ""
        if isinstance(call_event, BashOutput):
            call_text = call_event.command
        elif isinstance(call_event, ToolCall):
            call_text = str(call_event.input_params)

        if not _VERIFICATION_PATTERNS.search(call_text):
            continue

        # Check if the result is empty/zero
        content = event.content.strip().lower()
        is_empty = content in _EMPTY_PATTERNS or len(content) == 0

        if not is_empty:
            continue

        # Check that the next non-ToolResult event is NOT a UserPrompt
        for k in range(i + 1, min(len(events), i + 5)):
            if isinstance(events[k], ToolResult):
                continue
            if isinstance(events[k], UserPrompt):
                break  # User flagged it — not an anomaly
            # Agent continued without flagging
            anomalies.append({
                "session_id": session_id,
                "rule_id": "verification_returned_empty",
                "event_index": i,
                "timestamp": event.timestamp,
                "excerpt": _excerpt(event) or "(empty result)",
                "details": {
                    "call_command": call_text[:200],
                    "result_content": content[:200],
                },
            })
            break

    return anomalies


# ---------------------------------------------------------------------------
# Rule 4: scope_expansion (reserved — not implementable mechanically)
# ---------------------------------------------------------------------------

def rule_scope_expansion(events: list[Event], session_id: str) -> list[dict[str, Any]]:
    """Reserved. Not implementable mechanically at this phase.

    diff_intent_vs_execution (tool 7) partially covers this by comparing
    prompt mentions to files actually touched.
    """
    return []


# ---------------------------------------------------------------------------
# Rule 5: silent_error
# ---------------------------------------------------------------------------

def rule_silent_error(events: list[Event], session_id: str) -> list[dict[str, Any]]:
    """A ToolResult with error, followed by a ToolCall (agent continued past the error)."""
    anomalies: list[dict[str, Any]] = []

    for i, event in enumerate(events):
        if not isinstance(event, ToolResult):
            continue
        if event.success and not event.error:
            continue

        # Check next event (skip other ToolResults)
        for k in range(i + 1, min(len(events), i + 5)):
            if isinstance(events[k], ToolResult):
                continue
            if isinstance(events[k], UserPrompt):
                break  # Error was surfaced to user
            if isinstance(events[k], (ToolCall, BashOutput, FileEdit)):
                # Agent continued past the error
                anomalies.append({
                    "session_id": session_id,
                    "rule_id": "silent_error",
                    "event_index": i,
                    "timestamp": event.timestamp,
                    "excerpt": _excerpt(event),
                    "details": {
                        "error": event.error or event.content[:200],
                        "next_event_type": type(events[k]).__name__,
                        "next_event_index": k,
                    },
                })
            break

    return anomalies


# ---------------------------------------------------------------------------
# Rule 6: hook_bypass_attempt
# ---------------------------------------------------------------------------

_BYPASS_PATTERNS = ["--no-verify", "SKIP=", "HUSKY=0", "git commit -n"]


def rule_hook_bypass_attempt(events: list[Event], session_id: str) -> list[dict[str, Any]]:
    """A bash command that attempts to bypass pre-commit hooks."""
    anomalies: list[dict[str, Any]] = []

    for i, event in enumerate(events):
        if not isinstance(event, BashOutput):
            continue
        for pattern in _BYPASS_PATTERNS:
            if pattern in event.command:
                anomalies.append({
                    "session_id": session_id,
                    "rule_id": "hook_bypass_attempt",
                    "event_index": i,
                    "timestamp": event.timestamp,
                    "excerpt": _excerpt(event),
                    "details": {"matched_pattern": pattern, "command": event.command[:200]},
                })
                break  # One anomaly per command

    return anomalies


# ---------------------------------------------------------------------------
# Rule 7: uncommitted_work_at_session_end
# ---------------------------------------------------------------------------

def rule_uncommitted_work_at_session_end(events: list[Event], session_id: str) -> list[dict[str, Any]]:
    """FileEdits near the end of session without a subsequent successful git commit."""
    anomalies: list[dict[str, Any]] = []

    # Find the last SessionBoundary with "end" subtype, or use the end of the list
    end_idx = len(events)
    for i in range(len(events) - 1, -1, -1):
        if isinstance(events[i], SessionBoundary) and events[i].boundary_type == "end":
            end_idx = i
            break

    # Look at last 5 events before the end boundary
    start_idx = max(0, end_idx - 5)
    tail = events[start_idx:end_idx]

    # Find the last successful git commit in the entire session
    last_commit_idx = -1
    for i, event in enumerate(events):
        if isinstance(event, BashOutput) and "git commit" in event.command:
            corr = _find_correlated_result(events, i)
            if corr and (corr[1].success or "failed" not in corr[1].content.lower()):
                last_commit_idx = i

    # Check for FileEdits in the tail that are after the last commit
    uncommitted_files: list[str] = []
    last_edit_idx = -1
    for j, event in enumerate(tail):
        actual_idx = start_idx + j
        if isinstance(event, FileEdit) and actual_idx > last_commit_idx:
            uncommitted_files.append(event.file_path)
            last_edit_idx = actual_idx

    if uncommitted_files and last_edit_idx >= 0:
        anomalies.append({
            "session_id": session_id,
            "rule_id": "uncommitted_work_at_session_end",
            "event_index": last_edit_idx,
            "timestamp": events[last_edit_idx].timestamp,
            "excerpt": _excerpt(events[last_edit_idx]),
            "details": {"uncommitted_files": uncommitted_files},
        })

    return anomalies


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_ALL_RULES = [
    rule_hook_fire_with_silent_fix,
    rule_test_skip_added,
    rule_verification_returned_empty,
    rule_scope_expansion,
    rule_silent_error,
    rule_hook_bypass_attempt,
    rule_uncommitted_work_at_session_end,
]


def run_all_rules(events: list[Event], session_id: str) -> list[dict[str, Any]]:
    """Run all anomaly detection rules and return combined results."""
    results: list[dict[str, Any]] = []
    for rule in _ALL_RULES:
        results.extend(rule(events, session_id))
    return results
