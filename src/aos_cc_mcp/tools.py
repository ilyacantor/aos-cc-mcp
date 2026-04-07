"""Tier 0 read tools for the AOS CC MCP server.

All tools in this module are read-only (Tier 0) and always available
regardless of server mode. Every tool is registered via register_tool_tier()
at module load time.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
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
from .middleware import register_tool_tier
from .modes import Tier
from .parser import parse_session
from .server import mcp

logger = logging.getLogger(__name__)

SESSIONS_BASE = Path.home() / ".claude" / "projects"

# ---------------------------------------------------------------------------
# Tier registration — every tool registered at module load
# ---------------------------------------------------------------------------
register_tool_tier("list_sessions", Tier.T0)
register_tool_tier("session_summary", Tier.T0)
register_tool_tier("read_session", Tier.T0)
register_tool_tier("search_sessions", Tier.T0)
register_tool_tier("extract_commits", Tier.T0)
register_tool_tier("detect_anomalies", Tier.T0)
register_tool_tier("diff_intent_vs_execution", Tier.T0)

# Tier 2 write tools
register_tool_tier("dispatch_cc_session", Tier.T2)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _list_session_files() -> list[tuple[Path, str]]:
    """Find all session JSONL files under SESSIONS_BASE.

    Returns (file_path, project_dir_name) pairs.
    Excludes subagent session files.
    """
    results: list[tuple[Path, str]] = []
    if not SESSIONS_BASE.exists():
        return results
    for project_dir in SESSIONS_BASE.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl in project_dir.glob("*.jsonl"):
            results.append((jsonl, project_dir.name))
    return results


def _find_session_file(session_id: str) -> Path | None:
    """Locate a session JSONL file by its UUID stem."""
    for path, _ in _list_session_files():
        if path.stem == session_id:
            return path
    return None


def _get_tool_use_id(event: Event) -> str | None:
    """Extract tool_use_id from an event's raw dict.

    For ToolCall/BashOutput/FileEdit (assistant tool_use): raw.message.content[i].id
    For ToolResult (user tool_result): raw.message.content[i].tool_use_id
    """
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


def _event_type_name(event: Event) -> str:
    """Get the class name of an event."""
    return type(event).__name__


def _classify_unknown_subtype(event: Unknown) -> str:
    """Determine the subtype of an Unknown event from its raw dict structure."""
    raw = event.raw
    event_type = raw.get("type", "")

    # CC harness internal types
    if event_type in ("custom-title", "agent-name", "queue-operation"):
        return "harness_internal"

    # Attachment deltas (deferred tools, MCP instructions, skill deltas)
    if event_type == "attachment" or raw.get("attachment"):
        return "attachment_delta"

    # Assistant messages (text or thinking)
    if event_type == "assistant":
        content = raw.get("message", {}).get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "thinking":
                    return "assistant_thinking"
        return "assistant_text"

    return "other"


def _event_to_summary_dict(event: Event, index: int) -> dict[str, Any]:
    """Serialize event to a compact dict (no bodies) for 'events' verbosity."""
    d: dict[str, Any] = {
        "index": index,
        "event_type": _event_type_name(event),
        "timestamp": event.timestamp,
    }
    if isinstance(event, ToolCall):
        d["tool_name"] = event.tool_name
        d["tool_use_id"] = _get_tool_use_id(event)
    elif isinstance(event, BashOutput):
        d["tool_name"] = "Bash"
        d["tool_use_id"] = _get_tool_use_id(event)
    elif isinstance(event, ToolResult):
        d["tool_use_id"] = _get_tool_use_id(event)
    elif isinstance(event, Unknown):
        d["subtype"] = _classify_unknown_subtype(event)
    return d


def _event_to_full_dict(event: Event, index: int) -> dict[str, Any]:
    """Serialize event to a full dict with all structured fields."""
    d: dict[str, Any] = {
        "index": index,
        "event_type": _event_type_name(event),
        "timestamp": event.timestamp,
    }
    if isinstance(event, UserPrompt):
        d["text"] = event.text
    elif isinstance(event, ToolCall):
        d["tool_name"] = event.tool_name
        d["input_params"] = event.input_params
    elif isinstance(event, ToolResult):
        d["content"] = event.content
        d["success"] = event.success
        d["error"] = event.error
    elif isinstance(event, FileEdit):
        d["file_path"] = event.file_path
        d["before"] = event.before
        d["after"] = event.after
    elif isinstance(event, BashOutput):
        d["command"] = event.command
        d["stdout"] = event.stdout
        d["stderr"] = event.stderr
        d["exit_code"] = event.exit_code
    elif isinstance(event, SessionBoundary):
        d["boundary_type"] = event.boundary_type
    elif isinstance(event, Unknown):
        pass  # raw is excluded from full — it's too noisy
    return d


def _extract_searchable_text(event: Event) -> str:
    """Get searchable text content from parsed event fields."""
    if isinstance(event, UserPrompt):
        return event.text
    if isinstance(event, ToolCall):
        return json.dumps(event.input_params, default=str)
    if isinstance(event, ToolResult):
        return event.content
    if isinstance(event, BashOutput):
        return f"{event.command} {event.stdout} {event.stderr}"
    if isinstance(event, FileEdit):
        return f"{event.file_path} {event.before} {event.after}"
    return ""


def _parse_iso(dt_str: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime string, tolerant of format variants.

    Always returns UTC-aware datetimes. Naive inputs are assumed UTC.
    """
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _session_metadata(path: Path, project_dir: str) -> dict[str, Any] | None:
    """Build lightweight metadata for a session file (first 50 lines)."""
    try:
        events = parse_session(path, max_lines=50)
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
        return None

    user_prompts = [e for e in events if isinstance(e, UserPrompt)]
    tool_calls = [e for e in events if isinstance(e, (ToolCall, BashOutput, FileEdit))]
    timestamps = [_parse_iso(e.timestamp) for e in events if e.timestamp]
    timestamps = [t for t in timestamps if t is not None]

    start_time = min(timestamps).isoformat() if timestamps else None
    # For header scan, end_time is approximate (from first 50 lines only)
    approx_end = max(timestamps).isoformat() if timestamps else None

    first_prompt = user_prompts[0].text[:100] if user_prompts else None
    file_bytes = path.stat().st_size
    line_count = sum(1 for _ in open(path, "r", encoding="utf-8", errors="replace"))

    return {
        "session_id": path.stem,
        "project_dir": project_dir,
        "start_time": start_time,
        "approximate_end_time": approx_end,
        "file_line_count": line_count,
        "user_prompt_count": len(user_prompts),
        "tool_call_count": len(tool_calls),
        "first_prompt_preview": first_prompt,
        "file_bytes": file_bytes,
    }


def _full_session_stats(events: list[Event], path: Path, project_dir: str) -> dict[str, Any]:
    """Build full statistics from a completely parsed session."""
    user_prompts = [e for e in events if isinstance(e, UserPrompt)]
    tool_calls = [e for e in events if isinstance(e, (ToolCall, BashOutput, FileEdit))]
    file_edits = [e for e in events if isinstance(e, FileEdit)]
    bash_cmds = [e for e in events if isinstance(e, BashOutput)]

    timestamps = [_parse_iso(e.timestamp) for e in events if e.timestamp]
    timestamps = [t for t in timestamps if t is not None]
    start_time = min(timestamps).isoformat() if timestamps else None
    end_time = max(timestamps).isoformat() if timestamps else None

    duration = None
    if len(timestamps) >= 2:
        delta = max(timestamps) - min(timestamps)
        duration = round(delta.total_seconds() / 60, 2)

    files_touched = list(dict.fromkeys(e.file_path for e in file_edits))[:50]
    unique_cmds = list(dict.fromkeys(e.command[:100] for e in bash_cmds))[:50]

    # Count successful commits
    commit_count = 0
    for idx, e in enumerate(events):
        if _is_git_commit_bash(e):
            result = _find_correlated_result(events, e, idx)
            if result is None or result.success or "failed" not in result.content.lower():
                commit_count += 1

    return {
        "session_id": path.stem,
        "project_dir": project_dir,
        "start_time": start_time,
        "end_time": end_time,
        "duration_minutes": duration,
        "event_count": len(events),
        "user_prompt_count": len(user_prompts),
        "tool_call_count": len(tool_calls),
        "file_edit_count": len(file_edits),
        "bash_command_count": len(bash_cmds),
        "commit_count": commit_count,
        "first_prompt": user_prompts[0].text[:500] if user_prompts else None,
        "last_prompt": user_prompts[-1].text[:500] if user_prompts else None,
        "files_touched": files_touched,
        "bash_commands": unique_cmds,
    }


def _is_git_commit_bash(event: Event) -> bool:
    """Check if a BashOutput event is a git commit command."""
    return isinstance(event, BashOutput) and "git commit" in event.command


def _find_correlated_result(events: list[Event], call_event: Event, call_index: int) -> ToolResult | None:
    """Find the ToolResult that correlates to a ToolCall/BashOutput/FileEdit by tool_use_id."""
    call_id = _get_tool_use_id(call_event)
    if not call_id:
        return None
    # Search forward from the call event
    for e in events[call_index + 1:call_index + 20]:
        if isinstance(e, ToolResult) and _get_tool_use_id(e) == call_id:
            return e
    return None


# ---------------------------------------------------------------------------
# Tool 1: list_sessions
# ---------------------------------------------------------------------------

@mcp.tool()
def list_sessions(
    after: str | None = None,
    before: str | None = None,
    project_filter: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List Claude Code sessions from ~/.claude/projects/ with optional filtering.

    Read-only, Tier 0. Always available in all modes.

    Args:
        after: ISO 8601 datetime — only sessions starting on or after this time.
        before: ISO 8601 datetime — only sessions starting on or before this time.
        project_filter: Substring match against the project directory name.
        limit: Max sessions to return (default 50, hard cap 200).

    Returns:
        List of session metadata dicts sorted by start_time descending.
        file_line_count is the raw JSONL line count from a lightweight scan;
        for the true parsed event count, call session_summary.
        approximate_end_time reflects only the first 50 lines of the session.
    """
    limit = min(limit, 200)
    after_dt = _parse_iso(after)
    before_dt = _parse_iso(before)

    sessions: list[dict[str, Any]] = []
    for path, project_dir in _list_session_files():
        if project_filter and project_filter not in project_dir:
            continue

        meta = _session_metadata(path, project_dir)
        if meta is None:
            continue

        start_dt = _parse_iso(meta["start_time"])
        if after_dt and start_dt and start_dt < after_dt:
            continue
        if before_dt and start_dt and start_dt > before_dt:
            continue

        sessions.append(meta)

    # Sort by start_time descending (newest first)
    sessions.sort(key=lambda s: s.get("start_time") or "", reverse=True)
    return sessions[:limit]


# ---------------------------------------------------------------------------
# Tool 2: session_summary
# ---------------------------------------------------------------------------

@mcp.tool()
def session_summary(session_id: str) -> dict[str, Any]:
    """Produce a compact synthesis of one Claude Code session.

    Read-only, Tier 0. Always available in all modes.
    This is the workhorse tool for EOD scans.

    Args:
        session_id: The session UUID (filename stem).

    Returns:
        Summary dict with event counts, duration, files touched, and anomaly count.
    """
    path = _find_session_file(session_id)
    if path is None:
        return {"error": "session_not_found", "session_id": session_id}

    project_dir = path.parent.name
    try:
        events = parse_session(path)
    except Exception as exc:
        return {"error": "parse_failed", "session_id": session_id, "detail": str(exc)}

    stats = _full_session_stats(events, path, project_dir)

    # Count anomalies
    from .anomaly_rules import run_all_rules
    anomalies = run_all_rules(events, session_id)
    stats["anomaly_count"] = len(anomalies)

    return stats


# ---------------------------------------------------------------------------
# Tool 3: read_session
# ---------------------------------------------------------------------------

_SIZE_LIMIT = 100_000  # 100KB hard cap for 'full' verbosity

@mcp.tool()
def read_session(
    session_id: str,
    verbosity: str = "events",
) -> dict[str, Any] | list[dict[str, Any]]:
    """Return structured session content at one of three verbosity levels.

    Read-only, Tier 0. Always available in all modes.

    Args:
        session_id: The session UUID (filename stem).
        verbosity: One of "summary", "events", "full". Default "events".

    Returns:
        - summary: delegates to session_summary
        - events: list of compact event dicts (no bodies)
        - full: list of detailed event dicts (hard cap 100KB serialized)
    """
    if verbosity not in ("summary", "events", "full"):
        return {"error": "invalid_verbosity", "valid": ["summary", "events", "full"]}

    if verbosity == "summary":
        return session_summary(session_id)

    path = _find_session_file(session_id)
    if path is None:
        return {"error": "session_not_found", "session_id": session_id}

    try:
        events = parse_session(path)
    except Exception as exc:
        return {"error": "parse_failed", "session_id": session_id, "detail": str(exc)}

    if verbosity == "events":
        return [_event_to_summary_dict(e, i) for i, e in enumerate(events)]

    # verbosity == "full"
    full_list = [_event_to_full_dict(e, i) for i, e in enumerate(events)]
    serialized = json.dumps(full_list, default=str)
    if len(serialized.encode("utf-8")) > _SIZE_LIMIT:
        return {
            "error": "size_limit_exceeded",
            "bytes": len(serialized.encode("utf-8")),
            "limit": _SIZE_LIMIT,
            "suggestion": "use verbosity='events' or 'summary', or request a specific event range via a future tool",
        }
    return full_list


# ---------------------------------------------------------------------------
# Tool 4: search_sessions
# ---------------------------------------------------------------------------

@mcp.tool()
def search_sessions(
    query: str,
    after: str | None = None,
    before: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Keyword search across Claude Code sessions.

    Read-only, Tier 0. Always available in all modes.
    Searches UserPrompt text, ToolCall arguments, ToolResult content,
    BashOutput commands/output, and FileEdit paths/diffs.

    Args:
        query: Substring to search for (case-insensitive).
        after: ISO 8601 date filter.
        before: ISO 8601 date filter.
        limit: Max sessions to return (default 20, hard cap 50).

    Returns:
        List of match dicts ordered by match_count descending.
    """
    limit = min(limit, 50)
    after_dt = _parse_iso(after)
    before_dt = _parse_iso(before)
    query_lower = query.lower()

    matches: list[dict[str, Any]] = []
    for path, project_dir in _list_session_files():
        # Quick date filter from header
        meta = _session_metadata(path, project_dir)
        if meta is None:
            continue
        start_dt = _parse_iso(meta["start_time"])
        if after_dt and start_dt and start_dt < after_dt:
            continue
        if before_dt and start_dt and start_dt > before_dt:
            continue

        # Full parse for search
        try:
            events = parse_session(path)
        except Exception:
            continue

        match_count = 0
        first_match_index = -1
        first_match_excerpt = ""
        first_match_type = ""

        for i, event in enumerate(events):
            if isinstance(event, Unknown):
                continue  # Skip Unknown events to avoid noise
            text = _extract_searchable_text(event)
            if query_lower in text.lower():
                match_count += 1
                if first_match_index == -1:
                    first_match_index = i
                    first_match_type = _event_type_name(event)
                    # Extract excerpt around the match
                    pos = text.lower().find(query_lower)
                    start = max(0, pos - 80)
                    end = min(len(text), pos + len(query) + 80)
                    first_match_excerpt = text[start:end][:200]

        if match_count > 0:
            matches.append({
                "session_id": path.stem,
                "project_dir": project_dir,
                "match_count": match_count,
                "first_match_event_index": first_match_index,
                "first_match_excerpt": first_match_excerpt,
                "first_match_event_type": first_match_type,
            })

    matches.sort(key=lambda m: m["match_count"], reverse=True)
    return matches[:limit]


# ---------------------------------------------------------------------------
# Tool 5: extract_commits
# ---------------------------------------------------------------------------

@mcp.tool()
def extract_commits(
    session_id: str | None = None,
    after: str | None = None,
    before: str | None = None,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Extract git commit activity from sessions.

    Read-only, Tier 0. Always available in all modes.
    Detects commits by finding BashOutput events with 'git commit' commands
    and correlates them with ToolResult events by tool_use_id.

    Args:
        session_id: Specific session to scan. Mutually exclusive with after/before.
        after: ISO 8601 start of date range. Requires before.
        before: ISO 8601 end of date range. Requires after.

    Returns:
        List of commit dicts with hash, message, repo, and files changed.
    """
    # Validate input: exactly one mode
    if session_id and (after or before):
        return {"error": "provide session_id OR after+before, not both"}
    if not session_id and not (after and before):
        return {"error": "provide session_id OR both after and before"}

    if session_id:
        sessions_to_scan = [(session_id, _find_session_file(session_id))]
        if sessions_to_scan[0][1] is None:
            return {"error": "session_not_found", "session_id": session_id}
    else:
        after_dt = _parse_iso(after)
        before_dt = _parse_iso(before)
        sessions_to_scan = []
        for path, _ in _list_session_files():
            meta = _session_metadata(path, _)
            if meta is None:
                continue
            start_dt = _parse_iso(meta["start_time"])
            if after_dt and start_dt and start_dt < after_dt:
                continue
            if before_dt and start_dt and start_dt > before_dt:
                continue
            sessions_to_scan.append((path.stem, path))

    commits: list[dict[str, Any]] = []
    for sid, path in sessions_to_scan:
        if path is None:
            continue
        try:
            events = parse_session(path)
        except Exception:
            continue
        commits.extend(_extract_commits_from_events(events, sid))

    return commits


# Matches [branch hash] or [branch (root-commit) hash] in git commit output
_COMMIT_HASH_RE = re.compile(r"\[[\w/.-]+(?:\s+\([^)]+\))?\s+([0-9a-f]{7,40})\]")

# Matches cd <path> && or cd <path> ; prefix in bash commands
_CD_PREFIX_RE = re.compile(r"cd\s+([^\s&;|]+)\s*(?:&&|;)")


def _extract_repo_from_command(command: str, fallback: str | None) -> str | None:
    """Extract the repo path from a bash command's cd prefix.

    If the command starts with 'cd ~/code/foo && git commit ...', returns the
    expanded path. Falls back to the provided default if no cd prefix found.
    """
    m = _CD_PREFIX_RE.search(command)
    if m:
        raw_path = m.group(1)
        expanded = Path(raw_path).expanduser()
        return str(expanded)
    return fallback


def _extract_commits_from_events(events: list[Event], session_id: str) -> list[dict[str, Any]]:
    """Find git commits in a parsed event list."""
    commits: list[dict[str, Any]] = []

    for i, event in enumerate(events):
        if not _is_git_commit_bash(event):
            continue

        # Find correlated ToolResult for this git commit
        result = _find_correlated_result(events, event, i)
        result_text = result.content if result else ""

        # Parse commit hash from output — handles root-commit and normal format
        commit_hash = None
        message = None
        hash_match = _COMMIT_HASH_RE.search(result_text)
        if hash_match:
            commit_hash = hash_match.group(1)
        # Message is often after the hash bracket
        msg_match = re.search(r"\[[^\]]+\]\s+(.+?)(?:\n|$)", result_text)
        if msg_match:
            message = msg_match.group(1).strip()

        # Infer repo: first try cd prefix in the command, then cwd from raw
        raw_cwd = event.raw.get("cwd") or event.raw.get("message", {}).get("cwd")
        repo = _extract_repo_from_command(event.command, raw_cwd)

        # Collect preceding FileEdit events as files_changed
        files_changed: list[str] = []
        for j in range(max(0, i - 30), i):
            if isinstance(events[j], FileEdit):
                if events[j].file_path not in files_changed:
                    files_changed.append(events[j].file_path)

        commits.append({
            "session_id": session_id,
            "timestamp": event.timestamp,
            "commit_hash": commit_hash,
            "repo": repo,
            "message": message,
            "files_changed": files_changed,
        })

    return commits


# ---------------------------------------------------------------------------
# Tool 6: detect_anomalies
# ---------------------------------------------------------------------------

@mcp.tool()
def detect_anomalies(
    session_id: str | None = None,
    after: str | None = None,
    before: str | None = None,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Flag mechanically-detectable anomaly patterns in session events.

    Read-only, Tier 0. Always available in all modes.
    Each rule is mechanical pattern matching — no judgment calls.
    The coordinator interprets the flags.

    Seven rules: hook_fire_with_silent_fix, test_skip_added,
    verification_returned_empty, scope_expansion (reserved),
    silent_error, hook_bypass_attempt, uncommitted_work_at_session_end.

    Args:
        session_id: Specific session to scan. Mutually exclusive with after/before.
        after: ISO 8601 start of date range. Requires before.
        before: ISO 8601 end of date range. Requires after.

    Returns:
        List of anomaly dicts with rule_id, event_index, excerpt, and details.
    """
    if session_id and (after or before):
        return {"error": "provide session_id OR after+before, not both"}
    if not session_id and not (after and before):
        return {"error": "provide session_id OR both after and before"}

    from .anomaly_rules import run_all_rules

    if session_id:
        path = _find_session_file(session_id)
        if path is None:
            return {"error": "session_not_found", "session_id": session_id}
        try:
            events = parse_session(path)
        except Exception as exc:
            return {"error": "parse_failed", "session_id": session_id, "detail": str(exc)}
        return run_all_rules(events, session_id)

    # Date range mode
    after_dt = _parse_iso(after)
    before_dt = _parse_iso(before)
    all_anomalies: list[dict[str, Any]] = []
    for path, _ in _list_session_files():
        meta = _session_metadata(path, _)
        if meta is None:
            continue
        start_dt = _parse_iso(meta["start_time"])
        if after_dt and start_dt and start_dt < after_dt:
            continue
        if before_dt and start_dt and start_dt > before_dt:
            continue
        try:
            events = parse_session(path)
        except Exception:
            continue
        all_anomalies.extend(run_all_rules(events, path.stem))

    return all_anomalies


# ---------------------------------------------------------------------------
# Tool 7: diff_intent_vs_execution
# ---------------------------------------------------------------------------

# Fallback regex: only matches file paths with known extensions
_FILE_EXT_PATTERN = re.compile(
    r"[\w./-]+\.(?:py|ts|tsx|js|jsx|md|yaml|yml|json|toml|css|html|sh|sql|csv)"
)


def _decode_project_dir(project_dir_name: str) -> Path | None:
    """Decode a CC project directory name back to a filesystem path.

    CC encodes paths by replacing '/' with '-', so '-home-ilyac-code-console'
    becomes '/home/ilyac/code/console'. Returns None if the decoded path
    does not exist on disk.
    """
    if not project_dir_name or not project_dir_name.startswith("-"):
        return None
    decoded = "/" + project_dir_name[1:].replace("-", "/")
    p = Path(decoded)
    if p.is_dir():
        return p
    return None


def _git_ls_files(repo_path: Path) -> set[str] | None:
    """Run git ls-files in a repo and return the set of tracked file paths.

    This is the single allowed shell exception for Tier 0 tools — documented
    in CLAUDE.md under 'Tier 0 shell exceptions'. Returns None on failure.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        files = set(result.stdout.strip().splitlines())
        return files if files else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _extract_mentions_via_lookup(prompt: str, tracked_files: set[str]) -> list[str]:
    """Match prompt text against a set of tracked file paths.

    A file is 'mentioned' if its basename or relative path appears as a
    substring in the prompt.
    """
    basenames: dict[str, str] = {}  # basename -> relative path
    for f in tracked_files:
        bn = Path(f).name
        basenames[bn] = f

    mentioned: list[str] = []
    seen: set[str] = set()

    # Check relative paths first (more specific)
    for relpath in tracked_files:
        if relpath in prompt and relpath not in seen:
            mentioned.append(relpath)
            seen.add(relpath)

    # Then check basenames
    for bn, relpath in basenames.items():
        if bn in prompt and relpath not in seen:
            mentioned.append(relpath)
            seen.add(relpath)

    return mentioned


@mcp.tool()
def diff_intent_vs_execution(session_id: str) -> dict[str, Any]:
    """Compare what a session's first prompt requested vs what it actually did.

    Read-only, Tier 0. Always available in all modes.
    Uses git ls-files lookup when possible, falls back to filename regex.
    The extraction_mode field indicates which approach was used.

    Args:
        session_id: The session UUID (filename stem).

    Returns:
        Dict with intent vs execution comparison, file set differences,
        extraction_mode, and confidence field.
    """
    path = _find_session_file(session_id)
    if path is None:
        return {"error": "session_not_found", "session_id": session_id}

    try:
        events = parse_session(path)
    except Exception as exc:
        return {"error": "parse_failed", "session_id": session_id, "detail": str(exc)}

    project_dir = path.parent.name
    user_prompts = [e for e in events if isinstance(e, UserPrompt)]
    first_prompt = user_prompts[0].text if user_prompts else ""

    # Try git ls-files lookup first
    extraction_mode = "filename_regex_fallback"
    repo_path = _decode_project_dir(project_dir)
    tracked_files = None
    if repo_path:
        tracked_files = _git_ls_files(repo_path)

    if tracked_files:
        extraction_mode = "git_ls_files"
        files_mentioned = _extract_mentions_via_lookup(first_prompt, tracked_files)
    else:
        # Fallback: file-extension-only regex (no CamelCase/snake_case)
        mentions = _FILE_EXT_PATTERN.findall(first_prompt)
        files_mentioned = list(dict.fromkeys(mentions))

    # Files actually touched
    file_edits = [e for e in events if isinstance(e, FileEdit)]
    files_touched = list(dict.fromkeys(e.file_path for e in file_edits))

    # Set differences (use basenames for comparison since prompt mentions
    # may not include full paths)
    mentioned_basenames = {Path(f).name for f in files_mentioned}
    touched_basenames = {Path(f).name for f in files_touched}

    in_prompt_not_touched = [f for f in files_mentioned if Path(f).name not in touched_basenames]
    touched_not_in_prompt = [f for f in files_touched if Path(f).name not in mentioned_basenames]

    # Bash commands
    bash_events = [e for e in events if isinstance(e, BashOutput)]
    bash_commands = list(dict.fromkeys(e.command[:100] for e in bash_events))

    # Commits count
    commits_made = sum(1 for e in events if _is_git_commit_bash(e))

    return {
        "session_id": session_id,
        "first_prompt": first_prompt,
        "files_mentioned_in_prompt": files_mentioned,
        "files_actually_touched": files_touched,
        "files_in_prompt_not_touched": in_prompt_not_touched,
        "files_touched_not_in_prompt": touched_not_in_prompt,
        "bash_commands_run": bash_commands,
        "commits_made": commits_made,
        "extraction_mode": extraction_mode,
        "confidence": "heuristic",
    }


# ---------------------------------------------------------------------------
# Tool 8: dispatch_cc_session (Tier 2)
# ---------------------------------------------------------------------------

@mcp.tool()
def dispatch_cc_session(
    prompt: str,
    repo: str,
    timeout_seconds: int = 600,
    model: str | None = None,
    confirm_token: str | None = None,
) -> dict[str, Any]:
    """Dispatch a headless Claude Code session and return the result.

    Tier 2 — requires Approve or YOLO mode. Blocked in Plan mode.
    Spawns claude -p <prompt> in the specified repo, waits for completion,
    and returns session ID, exit code, and output tail for follow-up reads.

    Args:
        prompt: The prompt to send to Claude Code (max 50,000 chars).
        repo: Repo name under ~/code/ (alphanumeric, hyphens, underscores only).
        timeout_seconds: Max wait in seconds (30-1800, default 600). Clamped if out of range.
        model: Optional model override — "sonnet", "opus", or "haiku".
        confirm_token: Required in Approve mode, ignored in YOLO mode.

    Returns:
        Dict with session_id, exit_code, duration_seconds, timed_out,
        stdout_tail, stderr_tail, session_log_path, and warnings.
    """
    from .dispatch import run_dispatch
    from .server import audit_log

    return run_dispatch(
        prompt=prompt,
        repo=repo,
        timeout_seconds=timeout_seconds,
        model=model,
        audit_log=audit_log,
    )
