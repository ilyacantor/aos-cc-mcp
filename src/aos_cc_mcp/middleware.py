"""MCP middleware for audit logging and mode enforcement.

Intercepts all tool calls to:
1. Log the operation to the audit log
2. Check the tool's tier against the current mode
3. Block or allow based on the mode manager's decision
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

if TYPE_CHECKING:
    import mcp.types as mt
    from mcp.types import Tool

    from .audit import AuditLog
    from .modes import ModeManager, Tier

logger = logging.getLogger(__name__)

# Tool name -> Tier mapping. Populated by future phases as tools are registered.
# Phase 1b ships with an empty registry. Future phases add entries as tools land.
_tool_tiers: dict[str, "Tier"] = {}


def register_tool_tier(tool_name: str, tier: "Tier") -> None:
    """Register a tool's tier for mode enforcement. Called during tool registration."""
    _tool_tiers[tool_name] = tier


def get_tool_tier(tool_name: str) -> "Tier | None":
    """Look up a tool's tier. Returns None if unregistered."""
    return _tool_tiers.get(tool_name)


class AuditMiddleware(Middleware):
    """Logs all tool calls to the audit log."""

    def __init__(self, audit_log: "AuditLog", mode_manager: "ModeManager") -> None:
        self._audit = audit_log
        self._modes = mode_manager

    async def on_call_tool(
        self,
        context: "MiddlewareContext[mt.CallToolRequestParams]",
        call_next: "CallNext[mt.CallToolRequestParams, mt.CallToolResult]",
    ) -> "mt.CallToolResult":
        tool_name = context.message.name
        tier = get_tool_tier(tool_name)
        mode = self._modes.mode

        # Log the attempt
        self._audit.log(
            operation=f"call_tool:{tool_name}",
            mode=mode.value,
            details={"tier": tier.value if tier else "unregistered"},
        )

        # Unregistered tools are blocked — fail safe
        if tier is None:
            self._audit.log(
                operation=f"call_tool:{tool_name}",
                mode=mode.value,
                success=False,
                error="tool not registered in tier registry — add register_tool_tier() call during tool definition",
            )
            raise PermissionError(
                f"Tool '{tool_name}' is not registered in the tier registry. "
                "Add a register_tool_tier() call during tool definition."
            )

        # Enforce mode rules against registered tier
        from .modes import ToolDecision

        decision = self._modes.evaluate(tier)

        if decision == ToolDecision.BLOCKED_BY_TIER:
            self._audit.log(
                operation=f"call_tool:{tool_name}",
                mode=mode.value,
                success=False,
                error=f"Tier {tier.value} is constitutionally prohibited",
            )
            raise PermissionError(
                f"Tool '{tool_name}' is Tier {tier.value} — constitutionally prohibited. "
                "This restriction cannot be lifted without a new constitutional prompt."
            )

        if decision == ToolDecision.BLOCKED_BY_MODE:
            self._audit.log(
                operation=f"call_tool:{tool_name}",
                mode=mode.value,
                success=False,
                error=f"Tier {tier.value} blocked in {mode.value} mode",
            )
            raise PermissionError(
                f"Tool '{tool_name}' is Tier {tier.value} — not allowed in {mode.value} mode. "
                f"Current mode: {mode.value}. Required: approve or yolo."
            )

        if decision == ToolDecision.NEEDS_CONFIRMATION:
            # In Phase 1b, we log the need for confirmation but allow the call.
            # The actual confirmation mechanism (client-side) lands in Phase 3.
            self._audit.log(
                operation=f"call_tool:{tool_name}:confirmation_required",
                mode=mode.value,
                details={"tier": tier.value, "note": "confirmation mechanism deferred to Phase 3"},
            )
            logger.warning(
                "Tool '%s' (Tier %s) needs confirmation in %s mode — "
                "confirmation mechanism not yet implemented (Phase 3)",
                tool_name,
                tier.value,
                mode.value,
            )

        result = await call_next(context)

        # Log success
        self._audit.log(
            operation=f"call_tool:{tool_name}:completed",
            mode=mode.value,
            success=True,
        )

        return result
