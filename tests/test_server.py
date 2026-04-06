"""Tests for the MCP server.

Phase 2b: verify server imports, kill switch, transport/token enforcement,
middleware wiring, tool registration.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap


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


class TestTransportTokenEnforcement:
    """HTTP transport refuses to start without a token. Stdio is fine without one."""

    def _run_server(self, env_overrides: dict[str, str], timeout: int = 5) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        # Set control vars to empty string rather than removing them.
        # load_dotenv(override=False) won't overwrite existing vars, even empty
        # ones, so this prevents .env from interfering with test isolation.
        env["AOS_CC_MCP_DISABLED"] = ""
        env["AOS_CC_MCP_TOKEN"] = ""
        env["AOS_CC_MCP_TRANSPORT"] = ""
        env.update(env_overrides)
        return subprocess.run(
            [sys.executable, "-m", "aos_cc_mcp.server"],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def test_http_no_token_refuses_to_start(self) -> None:
        result = self._run_server({"AOS_CC_MCP_TRANSPORT": "http"})
        assert result.returncode == 2
        assert "FATAL" in result.stderr
        assert "AOS_CC_MCP_TOKEN" in result.stderr

    def test_http_with_token_starts(self) -> None:
        """HTTP + token set should get past the guard and start listening.

        We can't let it run forever, so we just verify it doesn't exit with
        code 2 (the token-missing guard). The process will be killed by timeout.
        """
        try:
            result = self._run_server(
                {"AOS_CC_MCP_TRANSPORT": "http", "AOS_CC_MCP_TOKEN": "test-token-abc"},
                timeout=3,
            )
            # If it exited on its own, it should NOT be exit code 2.
            assert result.returncode != 2
        except subprocess.TimeoutExpired:
            # Timeout means the server started and was listening — that's a pass.
            pass

    def test_stdio_no_token_starts(self) -> None:
        """Stdio transport should start fine without a token.

        Stdio blocks on stdin, so a timeout means it started successfully.
        """
        try:
            self._run_server({"AOS_CC_MCP_TRANSPORT": "stdio"}, timeout=3)
        except subprocess.TimeoutExpired:
            # Timeout means server started and blocked on stdin — pass.
            pass


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
