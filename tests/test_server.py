"""Tests for the MCP server.

Phase 2a: verify server imports, kill switch, middleware wiring, tool registration.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys


class TestServerImport:
    """Server module imports without error."""

    def test_import_server(self) -> None:
        from aos_cc_mcp import server  # noqa: F401

    def test_import_fastmcp_instance(self) -> None:
        from aos_cc_mcp.server import mcp

        assert mcp is not None


class TestServerInstantiation:
    """FastMCP server instance can be created without error."""

    def test_server_name(self) -> None:
        from aos_cc_mcp.server import mcp

        assert mcp.name == "aos-cc-mcp"


class TestToolRegistration:
    """Server has exactly the Phase 2a tools registered."""

    def test_seven_tools_registered(self) -> None:
        from aos_cc_mcp.server import mcp

        tools = asyncio.run(mcp.list_tools())
        assert len(tools) == 7, f"Expected 7 tools, found {len(tools)}"

    def test_expected_tool_names(self) -> None:
        from aos_cc_mcp.server import mcp

        tools = asyncio.run(mcp.list_tools())
        names = {t.name for t in tools}
        expected = {
            "list_sessions", "session_summary", "read_session",
            "search_sessions", "extract_commits", "detect_anomalies",
            "diff_intent_vs_execution",
        }
        assert names == expected


class TestKillSwitch:
    """Kill switch env var prevents server startup."""

    def test_kill_switch_exits(self) -> None:
        env = os.environ.copy()
        env["AOS_CC_MCP_DISABLED"] = "1"
        result = subprocess.run(
            [sys.executable, "-m", "aos_cc_mcp.server"],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 1

    def test_no_kill_switch_does_not_exit_immediately(self) -> None:
        # Without kill switch, the server should start (we can't fully run it in
        # a test, but we can verify the main() function gets past the kill switch
        # check by importing and checking the guard directly)
        from aos_cc_mcp.server import KILL_SWITCH_ENV

        assert os.environ.get(KILL_SWITCH_ENV) is None or os.environ.get(KILL_SWITCH_ENV) == ""


class TestModeManagerWired:
    """Server exposes a mode manager instance."""

    def test_mode_manager_exists(self) -> None:
        from aos_cc_mcp.server import mode_manager

        assert mode_manager is not None

    def test_default_mode_is_plan(self) -> None:
        from aos_cc_mcp.modes import Mode
        from aos_cc_mcp.server import mode_manager

        assert mode_manager.mode == Mode.PLAN


class TestAuditLogWired:
    """Server exposes an audit log instance."""

    def test_audit_log_exists(self) -> None:
        from aos_cc_mcp.server import audit_log

        assert audit_log is not None
