"""Tests for the AuditMiddleware — unregistered tool blocking and readonly audit logging."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from aos_cc_mcp.audit import AuditLog
from aos_cc_mcp.middleware import AuditMiddleware, get_tool_tier, register_tool_tier, _tool_tiers
from aos_cc_mcp.modes import Mode, ModeManager, Tier


def _make_context(tool_name: str) -> MagicMock:
    """Create a mock MiddlewareContext with the given tool name."""
    ctx = MagicMock()
    ctx.message.name = tool_name
    return ctx


class TestUnregisteredToolBlocked:
    """Unregistered tools must be denied, not passed through."""

    @pytest.fixture(autouse=True)
    def _clean_registry(self) -> None:
        """Ensure the tier registry is clean before and after each test."""
        saved = dict(_tool_tiers)
        _tool_tiers.clear()
        yield
        _tool_tiers.clear()
        _tool_tiers.update(saved)

    @pytest.mark.asyncio
    async def test_unregistered_tool_raises_permission_error(self, tmp_path: Path) -> None:
        audit = AuditLog(tmp_path / "audit.log")
        mm = ModeManager()
        mw = AuditMiddleware(audit, mm)

        ctx = _make_context("some_unregistered_tool")
        call_next = AsyncMock()

        with pytest.raises(PermissionError, match="not registered in the tier registry"):
            await mw.on_call_tool(ctx, call_next)

        # call_next must NOT have been called
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unregistered_tool_logged_to_audit(self, tmp_path: Path) -> None:
        audit = AuditLog(tmp_path / "audit.log")
        mm = ModeManager()
        mw = AuditMiddleware(audit, mm)

        ctx = _make_context("mystery_tool")
        call_next = AsyncMock()

        with pytest.raises(PermissionError):
            await mw.on_call_tool(ctx, call_next)

        entries = audit.read_entries()
        # Should have the attempt entry + the denial entry
        denial_entries = [e for e in entries if e.get("success") is False]
        assert len(denial_entries) == 1
        assert "not registered in tier registry" in denial_entries[0]["error"]
        assert denial_entries[0]["operation"] == "call_tool:mystery_tool"

    @pytest.mark.asyncio
    async def test_registered_tool_passes_through(self, tmp_path: Path) -> None:
        audit = AuditLog(tmp_path / "audit.log")
        mm = ModeManager()
        mm.set_mode(Mode.YOLO)
        mw = AuditMiddleware(audit, mm)

        register_tool_tier("registered_tool", Tier.T0)
        ctx = _make_context("registered_tool")
        call_next = AsyncMock(return_value=MagicMock())

        await mw.on_call_tool(ctx, call_next)

        call_next.assert_awaited_once()


class TestReadonlyAuditLogging:
    """Readonly mode changes are logged to the audit log."""

    def test_readonly_blocked_mode_change_logged(self, tmp_path: Path) -> None:
        audit = AuditLog(tmp_path / "audit.log")
        mm = ModeManager(readonly=True)

        # Attempt mode change — log it to audit
        mm.set_mode(Mode.YOLO)
        audit.log(
            operation="mode_change_blocked",
            mode=mm.mode.value,
            success=False,
            error="mode change blocked: AOS_CC_MCP_READONLY is active",
            details={"requested_mode": Mode.YOLO.value},
        )

        entries = audit.read_entries()
        blocked = [e for e in entries if e.get("operation") == "mode_change_blocked"]
        assert len(blocked) == 1
        assert blocked[0]["success"] is False
        assert "READONLY" in blocked[0]["error"]
        assert blocked[0]["details"]["requested_mode"] == "yolo"

        # Mode must still be Plan
        assert mm.mode == Mode.PLAN
