"""Operating mode state machine for the AOS CC MCP server.

Three modes: Plan (read-only), Approve (writes need confirmation), YOLO (writes allowed).
Default on startup is always Plan. Tier 3 is always prohibited regardless of mode.

State is file-backed at ~/.aos-cc-mcp/state.json. Every read hits the file.
set_mode writes atomically (tmp + rename). No env vars for mode.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path.home() / ".aos-cc-mcp" / "state.json"


class Mode(enum.Enum):
    """Server operating mode."""

    PLAN = "plan"
    APPROVE = "approve"
    YOLO = "yolo"


class Tier(enum.Enum):
    """Tool capability tier. Numeric value enables comparison."""

    T0 = 0  # Read-only, always available
    T1 = 1  # Low-blast-radius writes
    T2 = 2  # Meaningful writes
    T3 = 3  # Prohibited — constitutional ban


class ToolDecision(enum.Enum):
    """Result of evaluating a tool call against the current mode."""

    ALLOWED = "allowed"
    NEEDS_CONFIRMATION = "needs_confirmation"
    BLOCKED_BY_MODE = "blocked_by_mode"
    BLOCKED_BY_TIER = "blocked_by_tier"


class ModeManager:
    """Manages the server's operating mode and evaluates tool permissions.

    State is file-backed: every mode read hits ~/.aos-cc-mcp/state.json.
    set_mode writes atomically via tmp file + rename.
    Tier 3 tools are always blocked regardless of mode.
    When readonly is True, set_mode() is a no-op — mode stays Plan.
    """

    def __init__(self, readonly: bool = False, state_path: Path | None = None) -> None:
        self._state_path = state_path or DEFAULT_STATE_PATH
        self._readonly = readonly
        # Ensure parent dir exists
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        # Bootstrap: if file doesn't exist, write default
        if not self._state_path.exists():
            self._write_state(Mode.PLAN)
        if readonly:
            logger.warning(
                "READ-ONLY MODE ACTIVE — mode locked to Plan, "
                "writes disabled regardless of client requests"
            )

    def _read_state(self) -> Mode:
        """Read mode from the state file. Falls back to PLAN on corrupt/missing file."""
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            return Mode(data["mode"])
        except (json.JSONDecodeError, KeyError, ValueError, FileNotFoundError) as exc:
            logger.error(
                "Failed to read mode from %s (%s) — writing default Plan and continuing",
                self._state_path, exc,
            )
            self._write_state(Mode.PLAN)
            return Mode.PLAN

    def _write_state(self, mode: Mode) -> None:
        """Write mode to the state file atomically (write tmp, then rename)."""
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._state_path.parent), suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"mode": mode.value}, f)
            os.replace(tmp_path, str(self._state_path))
        except BaseException:
            # Clean up tmp on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @property
    def mode(self) -> Mode:
        if self._readonly:
            return Mode.PLAN
        return self._read_state()

    @property
    def readonly(self) -> bool:
        return self._readonly

    def set_mode(self, mode: Mode) -> None:
        if self._readonly:
            logger.warning(
                "Mode change to %s blocked: AOS_CC_MCP_READONLY is active — "
                "mode locked to Plan",
                mode.value,
            )
            return
        old = self._read_state()
        self._write_state(mode)
        logger.info("Mode changed: %s -> %s", old.value, mode.value)

    def evaluate(self, tier: Tier) -> ToolDecision:
        """Evaluate whether a tool of the given tier is allowed in the current mode.

        Returns a ToolDecision indicating whether the call is allowed,
        needs confirmation, or is blocked (and why).
        """
        # Tier 3 is always prohibited — constitutional rule
        if tier == Tier.T3:
            return ToolDecision.BLOCKED_BY_TIER

        # Tier 0 is always allowed in all modes
        if tier == Tier.T0:
            return ToolDecision.ALLOWED

        # Tiers 1 and 2 depend on mode
        current = self.mode
        if current == Mode.PLAN:
            return ToolDecision.BLOCKED_BY_MODE

        if current == Mode.APPROVE:
            return ToolDecision.NEEDS_CONFIRMATION

        if current == Mode.YOLO:
            return ToolDecision.ALLOWED

        return ToolDecision.BLOCKED_BY_MODE
