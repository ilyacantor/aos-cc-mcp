"""Append-only audit log for the AOS CC MCP server.

Every operation is logged. No log mutation — append only.
Log entries are JSONL (one JSON object per line).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_AUDIT_PATH = Path.home() / ".aos-cc-mcp" / "audit.log"


class AuditLog:
    """Append-only audit log writer.

    Writes one JSON line per operation. Never deletes, overwrites, or truncates.
    Parent directory is created on first write if it doesn't exist.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DEFAULT_AUDIT_PATH

    @property
    def path(self) -> Path:
        return self._path

    def log(
        self,
        operation: str,
        mode: str,
        *,
        success: bool = True,
        details: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Append one audit entry to the log file.

        Args:
            operation: What was attempted (e.g., "call_tool:list_sessions").
            mode: Current server mode at time of operation.
            success: Whether the operation succeeded.
            details: Arbitrary metadata about the operation.
            error: Error message if the operation failed.
        """
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "mode": mode,
            "success": success,
        }
        if details:
            entry["details"] = details
        if error:
            entry["error"] = error

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def read_entries(self) -> list[dict[str, Any]]:
        """Read all audit entries. For testing and inspection only."""
        if not self._path.exists():
            return []
        entries = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
