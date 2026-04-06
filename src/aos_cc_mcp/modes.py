"""Operating mode state machine for the AOS CC MCP server.

Three modes: Plan (read-only), Approve (writes need confirmation), YOLO (writes allowed).
Default on startup is always Plan. Tier 3 is always prohibited regardless of mode.
"""

from __future__ import annotations

import enum
import logging

logger = logging.getLogger(__name__)


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

    Always starts in Plan mode. Mode transitions are explicit.
    Tier 3 tools are always blocked regardless of mode.
    When readonly is True, set_mode() is a no-op — mode stays Plan.
    """

    def __init__(self, readonly: bool = False) -> None:
        self._mode = Mode.PLAN
        self._readonly = readonly
        if readonly:
            logger.warning(
                "READ-ONLY MODE ACTIVE — mode locked to Plan, "
                "writes disabled regardless of client requests"
            )

    @property
    def mode(self) -> Mode:
        return self._mode

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
        old = self._mode
        self._mode = mode
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
        if self._mode == Mode.PLAN:
            return ToolDecision.BLOCKED_BY_MODE

        if self._mode == Mode.APPROVE:
            return ToolDecision.NEEDS_CONFIRMATION

        if self._mode == Mode.YOLO:
            return ToolDecision.ALLOWED

        return ToolDecision.BLOCKED_BY_MODE
