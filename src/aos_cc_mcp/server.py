"""AOS CC MCP server skeleton.

Phase 1a: scaffolding only. No tools registered. The server instantiates
and can be started without error, but exposes zero capabilities.
"""

from fastmcp import FastMCP

mcp = FastMCP("aos-cc-mcp")


def main() -> None:
    """Entrypoint for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
