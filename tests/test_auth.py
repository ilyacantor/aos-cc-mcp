"""Tests for bearer token authentication."""

from __future__ import annotations

import asyncio
import os

from aos_cc_mcp.auth import ENV_VAR, EnvTokenAuth


class TestAuthDisabledWhenNoToken:
    """When AOS_CC_MCP_TOKEN is not set, auth is disabled."""

    def test_is_enabled_false(self, monkeypatch: object) -> None:
        # Use pytest monkeypatch to ensure env var is unset
        import pytest

        mp = pytest.MonkeyPatch()
        mp.delenv(ENV_VAR, raising=False)
        try:
            auth = EnvTokenAuth()
            assert auth.is_enabled is False
        finally:
            mp.undo()

    def test_any_token_accepted_when_disabled(self, monkeypatch: object) -> None:
        import pytest

        mp = pytest.MonkeyPatch()
        mp.delenv(ENV_VAR, raising=False)
        try:
            auth = EnvTokenAuth()
            result = asyncio.run(auth.verify_token("any-random-token"))
            assert result is not None
            assert result.client_id == "unauthenticated"
        finally:
            mp.undo()


class TestAuthEnabledWithToken:
    """When AOS_CC_MCP_TOKEN is set, only matching tokens are accepted."""

    def test_is_enabled_true(self) -> None:
        old = os.environ.get(ENV_VAR)
        try:
            os.environ[ENV_VAR] = "test-secret-token"
            auth = EnvTokenAuth()
            assert auth.is_enabled is True
        finally:
            if old is None:
                os.environ.pop(ENV_VAR, None)
            else:
                os.environ[ENV_VAR] = old

    def test_correct_token_accepted(self) -> None:
        old = os.environ.get(ENV_VAR)
        try:
            os.environ[ENV_VAR] = "test-secret-token"
            auth = EnvTokenAuth()
            result = asyncio.run(auth.verify_token("test-secret-token"))
            assert result is not None
            assert result.client_id == "coordinator"
        finally:
            if old is None:
                os.environ.pop(ENV_VAR, None)
            else:
                os.environ[ENV_VAR] = old

    def test_wrong_token_rejected(self) -> None:
        old = os.environ.get(ENV_VAR)
        try:
            os.environ[ENV_VAR] = "test-secret-token"
            auth = EnvTokenAuth()
            result = asyncio.run(auth.verify_token("wrong-token"))
            assert result is None
        finally:
            if old is None:
                os.environ.pop(ENV_VAR, None)
            else:
                os.environ[ENV_VAR] = old

    def test_empty_token_rejected(self) -> None:
        old = os.environ.get(ENV_VAR)
        try:
            os.environ[ENV_VAR] = "test-secret-token"
            auth = EnvTokenAuth()
            result = asyncio.run(auth.verify_token(""))
            assert result is None
        finally:
            if old is None:
                os.environ.pop(ENV_VAR, None)
            else:
                os.environ[ENV_VAR] = old
