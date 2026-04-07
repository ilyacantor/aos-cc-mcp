"""Regression test for the python -m double-import bug.

Running `python -m aos_cc_mcp.server` caused server.py to be loaded twice
(once as __main__, once as aos_cc_mcp.server when tools.py imported it),
creating two separate FastMCP instances. The running instance had zero tools.

This test verifies:
  1. __main__.py exists and loads without error
  2. __main__.main is the same function as server.main
  3. There is exactly one FastMCP instance after importing both server and tools
  4. That instance has exactly 7 tools with the expected names
"""

from __future__ import annotations

import asyncio


class TestPackageEntryPoint:
    """Verify __main__.py resolves the double-import problem."""

    def test_main_module_imports(self) -> None:
        import aos_cc_mcp.__main__  # noqa: F401

    def test_main_is_same_function(self) -> None:
        from aos_cc_mcp.__main__ import main as main_from_entry
        from aos_cc_mcp.server import main as main_from_server

        assert main_from_entry is main_from_server

    def test_single_mcp_instance(self) -> None:
        from aos_cc_mcp.server import mcp as mcp_from_server
        from aos_cc_mcp.tools import mcp as mcp_from_tools

        assert mcp_from_server is mcp_from_tools, (
            f"Double-import bug: server.mcp id={id(mcp_from_server)} "
            f"!= tools.mcp id={id(mcp_from_tools)}"
        )

    def test_seven_tools_registered_after_import(self) -> None:
        from aos_cc_mcp.server import mcp

        import aos_cc_mcp.tools  # noqa: F401

        tools = asyncio.run(mcp.list_tools())
        names = {t.name for t in tools}
        expected = {
            "list_sessions", "session_summary", "read_session",
            "search_sessions", "extract_commits", "detect_anomalies",
            "diff_intent_vs_execution",
        }
        assert len(tools) == 7, f"Expected 7 tools, got {len(tools)}"
        assert names == expected, f"Tool name mismatch: {names ^ expected}"
