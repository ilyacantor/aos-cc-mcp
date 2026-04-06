"""Tests for the MCP server skeleton.

Phase 1a: verify the server imports, instantiates, and has zero tools.
"""

from __future__ import annotations


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


class TestZeroTools:
    """Server has zero tools registered (explicit Phase 1a scope verification)."""

    def test_no_tools_registered(self) -> None:
        import asyncio

        from aos_cc_mcp.server import mcp

        tools = asyncio.run(mcp.list_tools())
        assert len(tools) == 0, f"Expected 0 tools, found {len(tools)}"
