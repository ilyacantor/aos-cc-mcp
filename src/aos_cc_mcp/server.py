"""AOS CC MCP server.

Phase 1b: security foundation wired in. Kill switch, bearer token auth,
mode system (Plan/Approve/YOLO), and append-only audit log.
Still zero tools registered — tools land in Phase 2+.
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

# --- Shared state ---
mode_manager = ModeManager()
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
