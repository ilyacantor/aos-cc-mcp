"""AOS CC MCP server.

Phase 2a: seven Tier 0 read tools registered on top of the Phase 1b
security foundation (kill switch, auth, mode system, audit log).
"""

from __future__ import annotations

import logging
import os
import sys

from fastmcp import FastMCP

from .audit import AuditLog
from .auth import EnvTokenAuth
from .middleware import AuditMiddleware
from .modes import ModeManager

logger = logging.getLogger(__name__)

KILL_SWITCH_ENV = "AOS_CC_MCP_DISABLED"
READONLY_ENV = "AOS_CC_MCP_READONLY"

_TRUTHY = {"1", "true", "yes"}


def _is_truthy(val: str | None) -> bool:
    return val is not None and val.strip().lower() in _TRUTHY


# --- Shared state ---
mode_manager = ModeManager(readonly=_is_truthy(os.environ.get(READONLY_ENV)))
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

    Checks the kill switch before starting. If AOS_CC_MCP_DISABLED is set
    to any non-empty value, the server refuses to start.
    """
    if os.environ.get(KILL_SWITCH_ENV):
        logger.critical(
            "%s is set — server refusing to start. "
            "Unset this environment variable to allow the server to run.",
            KILL_SWITCH_ENV,
        )
        sys.exit(1)

    audit_log.log(
        operation="server_start",
        mode=mode_manager.mode.value,
        details={"auth_enabled": EnvTokenAuth().is_enabled},
    )

    mcp.run()


if __name__ == "__main__":
    main()
