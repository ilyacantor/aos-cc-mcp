"""JSONL session log parser for Claude Code session files.

Reads a .jsonl file and produces a list of structured Event objects.
Format-tolerant: missing fields produce Unknown events with warnings, never crashes.
Every input line produces exactly one output event.
"""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger(__name__)


def parse_session(path: str | Path) -> list[Event]:
    """Parse a JSONL session file into a list of Events.

    Every line produces exactly one event. Malformed JSON lines become
    Unknown events. Missing fields degrade gracefully with warnings.
    """
    path = Path(path)
    events: list[Event] = []

    with path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                events.append(Unknown(timestamp=None, raw={"_empty_line": True, "_line_num": line_num}))
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("Line %d: malformed JSON — %s", line_num, exc)
                events.append(Unknown(timestamp=None, raw={"_parse_error": str(exc), "_raw_text": line, "_line_num": line_num}))
                continue

            event = _classify(data, line_num)
            events.append(event)

    return events


def _classify(data: dict[str, Any], line_num: int) -> Event:
    """Classify a parsed JSON dict into a typed Event."""
    event_type = data.get("type")
    timestamp = _extract_timestamp(data)

    # Session boundary types
    if event_type == "permission-mode":
        return SessionBoundary(boundary_type="start", timestamp=timestamp, raw=data)

    if event_type == "file-history-snapshot":
        return SessionBoundary(boundary_type="snapshot", timestamp=timestamp, raw=data)

    if event_type == "last-prompt":
        return SessionBoundary(boundary_type="end", timestamp=timestamp, raw=data)

    if event_type == "system":
        subtype = data.get("subtype", "")
        if subtype == "compact":
            return SessionBoundary(boundary_type="compaction", timestamp=timestamp, raw=data)
        return SessionBoundary(boundary_type=f"system:{subtype}" if subtype else "system", timestamp=timestamp, raw=data)

    # Attachment-only lines (deferred tools, MCP instructions, skill deltas)
    if event_type in ("attachment",) or (data.get("attachment") and event_type not in ("user", "assistant")):
        return SessionBoundary(boundary_type="attachment", timestamp=timestamp, raw=data)

    # User messages
    if event_type == "user":
        return _classify_user(data, timestamp, line_num)

    # Assistant messages
    if event_type == "assistant":
        return _classify_assistant(data, timestamp, line_num)

    # Anything else
    logger.warning("Line %d: unrecognized event type %r", line_num, event_type)
    return Unknown(timestamp=timestamp, raw=data)


def _classify_user(data: dict[str, Any], timestamp: str | None, line_num: int) -> Event:
    """Classify a user-type event. May contain a text prompt or tool results."""
    message = data.get("message", {})
    content = message.get("content", "")

    # Simple text prompt
    if isinstance(content, str):
        return UserPrompt(text=content, timestamp=timestamp, raw=data)

    # Content is a list — look for tool_result blocks
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                return _parse_tool_result(block, data, timestamp, line_num)

        # List content but no tool_result — treat as user prompt with structured content
        text = " ".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
        if text:
            return UserPrompt(text=text, timestamp=timestamp, raw=data)

    logger.warning("Line %d: user event with unparseable content structure", line_num)
    return Unknown(timestamp=timestamp, raw=data)


def _classify_assistant(data: dict[str, Any], timestamp: str | None, line_num: int) -> Event:
    """Classify an assistant-type event. May contain text, tool_use, or thinking."""
    message = data.get("message", {})
    content = message.get("content", [])

    if not isinstance(content, list):
        return Unknown(timestamp=timestamp, raw=data)

    # Find the most significant block in the content list.
    # Priority: tool_use > text > thinking > unknown
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            return _parse_tool_call(block, data, timestamp, line_num)

    # No tool_use found — it's a text/thinking assistant message.
    # These aren't tool calls; classify as Unknown (assistant text isn't
    # one of the 7 event types — it's metadata about the conversation).
    return Unknown(timestamp=timestamp, raw=data)


def _parse_tool_call(block: dict[str, Any], data: dict[str, Any], timestamp: str | None, line_num: int) -> Event:
    """Parse a tool_use block into a ToolCall, FileEdit, or BashOutput depending on the tool."""
    tool_name = block.get("name", "")
    input_params = block.get("input", {})

    # File edits (Edit or Write tools)
    if tool_name == "Edit":
        return FileEdit(
            file_path=input_params.get("file_path", ""),
            before=input_params.get("old_string", ""),
            after=input_params.get("new_string", ""),
            timestamp=timestamp,
            raw=data,
        )
    if tool_name == "Write":
        return FileEdit(
            file_path=input_params.get("file_path", ""),
            before="",
            after=input_params.get("content", ""),
            timestamp=timestamp,
            raw=data,
        )

    # Bash commands
    if tool_name == "Bash":
        return BashOutput(
            command=input_params.get("command", ""),
            stdout="",  # stdout comes in the tool_result, not the tool_use
            stderr="",
            exit_code=None,
            timestamp=timestamp,
            raw=data,
        )

    # All other tool calls
    return ToolCall(
        tool_name=tool_name,
        input_params=input_params,
        timestamp=timestamp,
        raw=data,
    )


def _parse_tool_result(block: dict[str, Any], data: dict[str, Any], timestamp: str | None, line_num: int) -> Event:
    """Parse a tool_result block into a ToolResult."""
    result_content = block.get("content", "")
    is_error = block.get("is_error", False)

    # Content may be a string or a list of content blocks
    if isinstance(result_content, list):
        text_parts = []
        for part in result_content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
        result_text = "\n".join(text_parts)
    elif isinstance(result_content, str):
        result_text = result_content
    else:
        result_text = str(result_content)

    return ToolResult(
        content=result_text,
        success=not is_error,
        error=result_text if is_error else None,
        timestamp=timestamp,
        raw=data,
    )


def _extract_timestamp(data: dict[str, Any]) -> str | None:
    """Extract timestamp from various locations in the event dict."""
    # Direct timestamp field
    ts = data.get("timestamp")
    if ts:
        return str(ts)

    # Nested in snapshot
    snapshot = data.get("snapshot", {})
    if isinstance(snapshot, dict):
        ts = snapshot.get("timestamp")
        if ts:
            return str(ts)

    # Nested in message
    message = data.get("message", {})
    if isinstance(message, dict):
        ts = message.get("timestamp")
        if ts:
            return str(ts)

    return None
