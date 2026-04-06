"""Bearer token authentication for the AOS CC MCP server.

Token is verified against the AOS_CC_MCP_TOKEN environment variable.
If the env var is not set, auth is disabled and a warning is logged.
Auth only applies to HTTP transport — stdio is inherently local.
"""

from __future__ import annotations

import logging
import os

from mcp.server.auth.provider import AccessToken

from fastmcp.server.auth import AuthProvider

logger = logging.getLogger(__name__)

ENV_VAR = "AOS_CC_MCP_TOKEN"


class EnvTokenAuth(AuthProvider):
    """Bearer token auth that checks against an environment variable.

    When AOS_CC_MCP_TOKEN is set, all HTTP requests must include a matching
    bearer token. When unset, auth is disabled (with a warning).
    """

    def __init__(self) -> None:
        super().__init__()
        self._token = os.environ.get(ENV_VAR)
        if not self._token:
            logger.warning(
                "%s is not set — bearer token auth is disabled. "
                "Set this env var before exposing the server over HTTP.",
                ENV_VAR,
            )

    @property
    def is_enabled(self) -> bool:
        return self._token is not None

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a bearer token against the configured env var.

        Returns an AccessToken if valid, None if invalid.
        """
        if not self._token:
            # Auth disabled — allow all
            return AccessToken(
                token=token,
                client_id="unauthenticated",
                scopes=["full"],
            )

        if token == self._token:
            return AccessToken(
                token=token,
                client_id="coordinator",
                scopes=["full"],
            )

        logger.warning("Bearer token verification failed — invalid token")
        return None
