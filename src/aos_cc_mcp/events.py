"""Event dataclasses representing parsed Claude Code JSONL session log entries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UserPrompt:
    """User input text."""

    text: str
    timestamp: str | None
    raw: dict[str, Any]


@dataclass
class ToolCall:
    """Assistant-initiated tool invocation."""

    tool_name: str
    input_params: dict[str, Any]
    timestamp: str | None
    raw: dict[str, Any]


@dataclass
class ToolResult:
    """Result returned from a tool invocation."""

    content: str
    success: bool
    error: str | None
    timestamp: str | None
    raw: dict[str, Any]


@dataclass
class FileEdit:
    """File modification via Edit or Write tool."""

    file_path: str
    before: str
    after: str
    timestamp: str | None
    raw: dict[str, Any]


@dataclass
class BashOutput:
    """Bash command execution and its output."""

    command: str
    stdout: str
    stderr: str
    exit_code: int | None
    timestamp: str | None
    raw: dict[str, Any]


@dataclass
class SessionBoundary:
    """Session lifecycle marker (start, end, compaction)."""

    boundary_type: str
    timestamp: str | None
    raw: dict[str, Any]


@dataclass
class Unknown:
    """Unclassifiable event — raw dict preserved verbatim."""

    timestamp: str | None
    raw: dict[str, Any]


# Union type for all events
Event = (
    UserPrompt
    | ToolCall
    | ToolResult
    | FileEdit
    | BashOutput
    | SessionBoundary
    | Unknown
)
