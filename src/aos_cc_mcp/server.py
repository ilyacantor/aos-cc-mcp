"""AOS CC MCP server.

Phase 2b: Streamable HTTP transport with bearer auth enforcement,
on top of the Phase 2a Tier 0 read tools and Phase 1b security foundation.

Transport is selected via AOS_CC_MCP_TRANSPORT:
  - "stdio" (default) — local stdio, no token required.
  - "http" — Streamable HTTP on 127.0.0.1:8765, token required.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the repo root (adjacent to pyproject.toml) if present.
# This must happen before any env var reads below.
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)

from fastmcp import FastMCP

from .audit import AuditLog
from .auth import ENV_VAR as TOKEN_ENV, EnvTokenAuth
from .middleware import AuditMiddleware
from .modes import ModeManager

logger = logging.getLogger(__name__)

KILL_SWITCH_ENV = "AOS_CC_MCP_DISABLED"
READONLY_ENV = "AOS_CC_MCP_READONLY"
TRANSPORT_ENV = "AOS_CC_MCP_TRANSPORT"

HTTP_HOST = "127.0.0.1"
HTTP_PORT = 8765

_TRUTHY = {"1", "true", "yes"}


def _is_truthy(val: str | None) -> bool:
    return val is not None and val.strip().lower() in _TRUTHY


def _get_transport() -> str:
    """Return the configured transport: 'stdio' (default) or 'http'."""
    val = os.environ.get(TRANSPORT_ENV, "stdio").strip().lower()
    if val not in ("stdio", "http"):
        logger.critical(
            "%s must be 'stdio' or 'http', got '%s'. Refusing to start.",
            TRANSPORT_ENV, val,
        )
        sys.exit(2)
    return val


# --- Shared state ---
mode_manager = ModeManager(readonly=_is_truthy(os.environ.get(READONLY_ENV)))  # file-backed, no env var for mode
audit_log = AuditLog()


def _build_server() -> FastMCP:
    """Build and configure the FastMCP server instance."""
    auth = EnvTokenAuth()

    server = FastMCP(
        "aos-cc-mcp",
        auth=auth if auth.is_enabled else None,
        middleware=[AuditMiddleware(audit_log, mode_manager)],
    )

    return server


mcp = _build_server()

# Import tools module to trigger @mcp.tool() registration and register_tool_tier() calls.
# This must happen AFTER mcp is created above.
from . import tools as _tools  # noqa: E402, F401


def main() -> None:
    """Entrypoint for the MCP server.

    Checks kill switch, then enforces token requirement for HTTP transport,
    then starts the server in the configured transport mode.
    """
    if os.environ.get(KILL_SWITCH_ENV):
        logger.critical(
            "%s is set — server refusing to start. "
            "Unset this environment variable to allow the server to run.",
            KILL_SWITCH_ENV,
        )
        sys.exit(1)

    transport = _get_transport()

    # HTTP transport requires a bearer token — refuse to start without one.
    if transport == "http" and not os.environ.get(TOKEN_ENV):
        print(
            "FATAL: HTTP transport requires AOS_CC_MCP_TOKEN to be set. "
            "Refusing to start an unauthenticated HTTP server. "
            "See CLAUDE.md 'Auth footgun' section.",
            file=sys.stderr,
        )
        sys.exit(2)

    audit_log.log(
        operation="server_start",
        mode=mode_manager.mode.value,
        details={
            "auth_enabled": EnvTokenAuth().is_enabled,
            "transport": transport,
        },
    )

    if transport == "http":
        logger.info(
            "Starting Streamable HTTP transport on %s:%d", HTTP_HOST, HTTP_PORT,
        )
        mcp.run(
            transport="streamable-http",
            host=HTTP_HOST,
            port=HTTP_PORT,
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()
