"""Tests for dispatch_cc_session — Tier 2 write tool."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from aos_cc_mcp.audit import AuditLog
from aos_cc_mcp.middleware import AuditMiddleware, _tool_tiers, get_tool_tier, register_tool_tier
from aos_cc_mcp.modes import Mode, ModeManager, Tier

import aos_cc_mcp.dispatch as dispatch_mod


# ---------------------------------------------------------------------------
# Repo validation
# ---------------------------------------------------------------------------


class TestRepoValidation:
    """Repo name must be [a-zA-Z0-9_-] and resolve to an existing directory."""

    def test_valid_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dispatch_mod, "_REPO_BASE", tmp_path)
        (tmp_path / "my-repo").mkdir()
        path = dispatch_mod._validate_repo("my-repo")
        assert path == tmp_path / "my-repo"

    def test_alphanumeric_underscore_hyphen(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dispatch_mod, "_REPO_BASE", tmp_path)
        (tmp_path / "My_Repo-123").mkdir()
        path = dispatch_mod._validate_repo("My_Repo-123")
        assert path == tmp_path / "My_Repo-123"

    def test_dotdot_rejected(self) -> None:
        with pytest.raises(ValueError, match="must match"):
            dispatch_mod._validate_repo("..")

    def test_slash_rejected(self) -> None:
        with pytest.raises(ValueError, match="must match"):
            dispatch_mod._validate_repo("foo/bar")

    def test_special_chars_rejected(self) -> None:
        with pytest.raises(ValueError, match="must match"):
            dispatch_mod._validate_repo("repo;rm")

    def test_space_rejected(self) -> None:
        with pytest.raises(ValueError, match="must match"):
            dispatch_mod._validate_repo("my repo")

    def test_dot_rejected(self) -> None:
        with pytest.raises(ValueError, match="must match"):
            dispatch_mod._validate_repo("repo.name")

    def test_tilde_rejected(self) -> None:
        with pytest.raises(ValueError, match="must match"):
            dispatch_mod._validate_repo("~root")

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError, match="must match"):
            dispatch_mod._validate_repo("")

    def test_missing_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dispatch_mod, "_REPO_BASE", tmp_path)
        with pytest.raises(ValueError, match="not found"):
            dispatch_mod._validate_repo("nonexistent")


# ---------------------------------------------------------------------------
# Prompt validation
# ---------------------------------------------------------------------------


class TestPromptValidation:
    """Prompt must be non-empty and under 50,000 chars."""

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            dispatch_mod._validate_prompt("")

    def test_oversized_rejected(self) -> None:
        with pytest.raises(ValueError, match="too long"):
            dispatch_mod._validate_prompt("x" * 50_001)

    def test_valid_prompt(self) -> None:
        assert dispatch_mod._validate_prompt("hello world") == "hello world"

    def test_max_length_accepted(self) -> None:
        prompt = "x" * 50_000
        assert dispatch_mod._validate_prompt(prompt) == prompt

    def test_whitespace_only_accepted(self) -> None:
        # Spec says "strip nothing" — whitespace-only is non-empty
        assert dispatch_mod._validate_prompt("   ") == "   "


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------


class TestModelValidation:
    """Model must be one of sonnet, opus, haiku or None (defaults to sonnet)."""

    def test_none_defaults_to_sonnet(self) -> None:
        assert dispatch_mod._validate_model(None) == "sonnet"

    def test_sonnet_accepted(self) -> None:
        assert dispatch_mod._validate_model("sonnet") == "sonnet"

    def test_opus_accepted(self) -> None:
        assert dispatch_mod._validate_model("opus") == "opus"

    def test_haiku_accepted(self) -> None:
        assert dispatch_mod._validate_model("haiku") == "haiku"

    def test_invalid_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid model"):
            dispatch_mod._validate_model("gpt-4")

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid model"):
            dispatch_mod._validate_model("")


# ---------------------------------------------------------------------------
# Timeout validation
# ---------------------------------------------------------------------------


class TestTimeoutValidation:
    """Timeout is clamped to [30, 1800] with warnings."""

    def test_valid_timeout(self) -> None:
        val, warnings = dispatch_mod._validate_timeout(300)
        assert val == 300
        assert warnings == []

    def test_below_minimum_clamped(self) -> None:
        val, warnings = dispatch_mod._validate_timeout(10)
        assert val == 30
        assert len(warnings) == 1
        assert "clamped to minimum" in warnings[0]

    def test_above_maximum_clamped(self) -> None:
        val, warnings = dispatch_mod._validate_timeout(5000)
        assert val == 1800
        assert len(warnings) == 1
        assert "clamped to maximum" in warnings[0]

    def test_boundary_min_accepted(self) -> None:
        val, warnings = dispatch_mod._validate_timeout(30)
        assert val == 30
        assert warnings == []

    def test_boundary_max_accepted(self) -> None:
        val, warnings = dispatch_mod._validate_timeout(1800)
        assert val == 1800
        assert warnings == []

    def test_zero_clamped(self) -> None:
        val, warnings = dispatch_mod._validate_timeout(0)
        assert val == 30
        assert len(warnings) == 1

    def test_negative_clamped(self) -> None:
        val, warnings = dispatch_mod._validate_timeout(-100)
        assert val == 30
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Tier registration
# ---------------------------------------------------------------------------


class TestTierRegistration:
    """dispatch_cc_session must be registered at Tier 2."""

    def test_registered_at_t2(self) -> None:
        tier = get_tool_tier("dispatch_cc_session")
        assert tier == Tier.T2


# ---------------------------------------------------------------------------
# Mode enforcement (middleware tests)
# ---------------------------------------------------------------------------


def _make_context(tool_name: str) -> MagicMock:
    ctx = MagicMock()
    ctx.message.name = tool_name
    return ctx


class TestModeEnforcement:
    """Middleware enforces mode rules for the Tier 2 dispatch tool."""

    @pytest.fixture(autouse=True)
    def _clean_registry(self) -> None:
        saved = dict(_tool_tiers)
        _tool_tiers.clear()
        yield
        _tool_tiers.clear()
        _tool_tiers.update(saved)

    @pytest.mark.asyncio
    async def test_plan_mode_blocks(self, tmp_path: Path) -> None:
        register_tool_tier("dispatch_cc_session", Tier.T2)
        audit = AuditLog(tmp_path / "audit.log")
        mm = ModeManager()  # Default: Plan
        mw = AuditMiddleware(audit, mm)

        ctx = _make_context("dispatch_cc_session")
        call_next = AsyncMock()

        with pytest.raises(PermissionError, match="not allowed in plan mode"):
            await mw.on_call_tool(ctx, call_next)

        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_approve_mode_needs_confirmation(self, tmp_path: Path) -> None:
        register_tool_tier("dispatch_cc_session", Tier.T2)
        audit = AuditLog(tmp_path / "audit.log")
        mm = ModeManager()
        mm.set_mode(Mode.APPROVE)
        mw = AuditMiddleware(audit, mm)

        ctx = _make_context("dispatch_cc_session")
        call_next = AsyncMock(return_value=MagicMock())

        # Phase 1b allows with a warning (confirmation mechanism deferred)
        await mw.on_call_tool(ctx, call_next)
        call_next.assert_awaited_once()

        entries = audit.read_entries()
        confirm_entries = [
            e for e in entries if "confirmation_required" in e.get("operation", "")
        ]
        assert len(confirm_entries) == 1

    @pytest.mark.asyncio
    async def test_yolo_mode_allows(self, tmp_path: Path) -> None:
        register_tool_tier("dispatch_cc_session", Tier.T2)
        audit = AuditLog(tmp_path / "audit.log")
        mm = ModeManager()
        mm.set_mode(Mode.YOLO)
        mw = AuditMiddleware(audit, mm)

        ctx = _make_context("dispatch_cc_session")
        call_next = AsyncMock(return_value=MagicMock())

        await mw.on_call_tool(ctx, call_next)
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_plan_mode_audit_logged(self, tmp_path: Path) -> None:
        register_tool_tier("dispatch_cc_session", Tier.T2)
        audit = AuditLog(tmp_path / "audit.log")
        mm = ModeManager()
        mw = AuditMiddleware(audit, mm)

        ctx = _make_context("dispatch_cc_session")
        call_next = AsyncMock()

        with pytest.raises(PermissionError):
            await mw.on_call_tool(ctx, call_next)

        entries = audit.read_entries()
        denial = [e for e in entries if e.get("success") is False]
        assert len(denial) == 1
        assert "blocked" in denial[0]["error"].lower()


# ---------------------------------------------------------------------------
# run_dispatch with mocked subprocess
# ---------------------------------------------------------------------------


class TestRunDispatch:
    """Core dispatch logic with mocked subprocess."""

    @pytest.fixture(autouse=True)
    def _setup_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dispatch_mod, "_REPO_BASE", tmp_path)
        (tmp_path / "test-repo").mkdir()

    def _mock_popen(self, monkeypatch: pytest.MonkeyPatch, returncode: int = 0,
                    stdout: bytes = b"output", stderr: bytes = b"") -> MagicMock:
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (stdout, stderr)
        mock_proc.returncode = returncode
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr(subprocess, "Popen", mock_popen)
        return mock_popen

    def test_successful_dispatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._mock_popen(monkeypatch)
        monkeypatch.setattr(dispatch_mod, "_find_session_log", lambda r, t: ("sid-123", "/p/sid-123.jsonl"))

        result = dispatch_mod.run_dispatch(prompt="test prompt", repo="test-repo")

        assert result["session_id"] == "sid-123"
        assert result["exit_code"] == 0
        assert result["timed_out"] is False
        assert result["session_log_path"] == "/p/sid-123.jsonl"
        assert result["warnings"] == []

    def test_popen_args_are_list_form(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_popen = self._mock_popen(monkeypatch)
        monkeypatch.setattr(dispatch_mod, "_find_session_log", lambda r, t: (None, None))

        dispatch_mod.run_dispatch(prompt="my prompt", repo="test-repo", model="opus")

        call_args = mock_popen.call_args
        args_list = call_args[0][0]  # First positional arg = argv list
        assert args_list == ["claude", "-p", "my prompt", "--model", "opus"]
        # Verify shell=True is NOT used
        assert call_args[1].get("shell") is None or call_args[1].get("shell") is False

    def test_default_model_is_sonnet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_popen = self._mock_popen(monkeypatch)
        monkeypatch.setattr(dispatch_mod, "_find_session_log", lambda r, t: (None, None))

        dispatch_mod.run_dispatch(prompt="test", repo="test-repo")

        args_list = mock_popen.call_args[0][0]
        assert args_list[-1] == "sonnet"

    def test_stdout_tail_truncated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        long_output = b"x" * 5000
        self._mock_popen(monkeypatch, stdout=long_output)
        monkeypatch.setattr(dispatch_mod, "_find_session_log", lambda r, t: (None, None))

        result = dispatch_mod.run_dispatch(prompt="test", repo="test-repo")

        assert len(result["stdout_tail"]) == 2000

    def test_nonzero_exit_code_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._mock_popen(monkeypatch, returncode=1, stderr=b"error occurred")
        monkeypatch.setattr(dispatch_mod, "_find_session_log", lambda r, t: (None, None))

        result = dispatch_mod.run_dispatch(prompt="test", repo="test-repo")

        assert result["exit_code"] == 1
        assert "error occurred" in result["stderr_tail"]

    def test_claude_not_on_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(subprocess, "Popen", MagicMock(side_effect=FileNotFoundError))

        result = dispatch_mod.run_dispatch(prompt="test", repo="test-repo")

        assert result["exit_code"] == -1
        assert "not found on PATH" in result["stderr_tail"]
        assert "not found on PATH" in result["warnings"][0]

    def test_timeout_clamping_in_warnings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._mock_popen(monkeypatch)
        monkeypatch.setattr(dispatch_mod, "_find_session_log", lambda r, t: (None, None))

        result = dispatch_mod.run_dispatch(prompt="test", repo="test-repo", timeout_seconds=5)

        assert any("clamped" in w for w in result["warnings"])

    def test_validation_error_on_bad_repo(self) -> None:
        with pytest.raises(ValueError, match="must match"):
            dispatch_mod.run_dispatch(prompt="test", repo="../etc")

    def test_validation_error_on_empty_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            dispatch_mod.run_dispatch(prompt="", repo="test-repo")

    def test_validation_error_on_bad_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(ValueError, match="Invalid model"):
            dispatch_mod.run_dispatch(prompt="test", repo="test-repo", model="gpt-4")


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


class TestAuditLogging:
    """Dispatch writes a completion audit entry without prompt content."""

    @pytest.fixture(autouse=True)
    def _setup_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dispatch_mod, "_REPO_BASE", tmp_path)
        (tmp_path / "test-repo").mkdir()
        self._tmp_path = tmp_path

    def test_completion_entry_logged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"done", b"")
        mock_proc.returncode = 0
        monkeypatch.setattr(subprocess, "Popen", MagicMock(return_value=mock_proc))
        monkeypatch.setattr(dispatch_mod, "_find_session_log", lambda r, t: ("fake-sid", "/p.jsonl"))

        audit = AuditLog(self._tmp_path / "audit.log")
        dispatch_mod.run_dispatch(prompt="secret prompt text", repo="test-repo", audit_log=audit)

        entries = audit.read_entries()
        completion = [e for e in entries if e["operation"] == "dispatch_cc_session:completed"]
        assert len(completion) == 1

        entry = completion[0]
        assert entry["details"]["repo"] == "test-repo"
        assert entry["details"]["exit_code"] == 0
        assert entry["details"]["session_id"] == "fake-sid"
        assert entry["details"]["timed_out"] is False
        assert entry["success"] is True

    def test_prompt_not_in_completion_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        monkeypatch.setattr(subprocess, "Popen", MagicMock(return_value=mock_proc))
        monkeypatch.setattr(dispatch_mod, "_find_session_log", lambda r, t: ("sid", "/p.jsonl"))

        audit = AuditLog(self._tmp_path / "audit.log")
        dispatch_mod.run_dispatch(prompt="TOP SECRET PROMPT CONTENT", repo="test-repo", audit_log=audit)

        entries = audit.read_entries()
        completion = [e for e in entries if e["operation"] == "dispatch_cc_session:completed"]
        serialized = json.dumps(completion[0])
        assert "TOP SECRET PROMPT CONTENT" not in serialized

    def test_failure_logged_on_claude_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(subprocess, "Popen", MagicMock(side_effect=FileNotFoundError))

        audit = AuditLog(self._tmp_path / "audit.log")
        dispatch_mod.run_dispatch(prompt="test", repo="test-repo", audit_log=audit)

        entries = audit.read_entries()
        completion = [e for e in entries if e["operation"] == "dispatch_cc_session:completed"]
        assert len(completion) == 1
        assert completion[0]["success"] is False
        assert "not found" in completion[0]["error"]

    @pytest.mark.asyncio
    async def test_middleware_and_tool_both_log(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Full path: middleware entry + tool completion, both in the audit log."""
        saved = dict(_tool_tiers)
        _tool_tiers.clear()
        try:
            register_tool_tier("dispatch_cc_session", Tier.T2)

            mock_proc = MagicMock()
            mock_proc.communicate.return_value = (b"done", b"")
            mock_proc.returncode = 0
            monkeypatch.setattr(subprocess, "Popen", MagicMock(return_value=mock_proc))
            monkeypatch.setattr(dispatch_mod, "_find_session_log", lambda r, t: ("sid", "/p.jsonl"))

            audit = AuditLog(self._tmp_path / "audit.log")
            mm = ModeManager()
            mm.set_mode(Mode.YOLO)
            mw = AuditMiddleware(audit, mm)

            ctx = _make_context("dispatch_cc_session")

            async def _call_next(_ctx: object) -> MagicMock:
                dispatch_mod.run_dispatch(
                    prompt="my prompt", repo="test-repo", audit_log=audit,
                )
                return MagicMock()

            await mw.on_call_tool(ctx, _call_next)

            entries = audit.read_entries()

            # Middleware entry (attempt)
            mw_entry = [e for e in entries if e["operation"] == "call_tool:dispatch_cc_session"]
            assert len(mw_entry) >= 1

            # Tool completion
            tool_completion = [e for e in entries if e["operation"] == "dispatch_cc_session:completed"]
            assert len(tool_completion) == 1
            assert "my prompt" not in json.dumps(tool_completion[0])

            # Middleware completion
            mw_completion = [e for e in entries if e["operation"] == "call_tool:dispatch_cc_session:completed"]
            assert len(mw_completion) == 1
        finally:
            _tool_tiers.clear()
            _tool_tiers.update(saved)


# ---------------------------------------------------------------------------
# Session log finder
# ---------------------------------------------------------------------------


class TestFindSessionLog:
    """_find_session_log locates the most recent JSONL file by mtime."""

    def test_finds_recent_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        sessions_dir = tmp_path / ".claude" / "projects" / "-home-ilyac-code-myrepo"
        sessions_dir.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        start = 1000.0
        log_file = sessions_dir / "abc-123.jsonl"
        log_file.write_text("{}\n")
        import os
        os.utime(log_file, (start + 10, start + 10))

        sid, path = dispatch_mod._find_session_log("myrepo", start)
        assert sid == "abc-123"
        assert path == str(log_file)

    def test_ignores_old_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        sessions_dir = tmp_path / ".claude" / "projects" / "-home-ilyac-code-myrepo"
        sessions_dir.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        start = 2000.0
        old_file = sessions_dir / "old.jsonl"
        old_file.write_text("{}\n")
        import os
        os.utime(old_file, (start - 100, start - 100))

        sid, path = dispatch_mod._find_session_log("myrepo", start)
        assert sid is None
        assert path is None

    def test_missing_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        sid, path = dispatch_mod._find_session_log("nonexistent", 0.0)
        assert sid is None
        assert path is None


# ---------------------------------------------------------------------------
# Integration test — real claude binary
# ---------------------------------------------------------------------------


class TestSubprocessIntegration:
    """Dispatch a real claude -p call. Marked slow, skipped if claude not on PATH."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_claude(self) -> None:
        if not shutil.which("claude"):
            pytest.skip("claude binary not on PATH")

    @pytest.mark.slow
    def test_dispatch_real_session(self, tmp_path: Path) -> None:
        audit = AuditLog(tmp_path / "audit.log")
        result = dispatch_mod.run_dispatch(
            prompt="Respond with the single word 'hello' and nothing else. Do not use any tools.",
            repo="aos-cc-mcp",
            timeout_seconds=120,
            model="haiku",
            audit_log=audit,
        )

        assert result["exit_code"] == 0, f"claude exited with {result['exit_code']}: {result['stderr_tail']}"
        assert result["timed_out"] is False
        assert result["session_id"] is not None, "No session log found after dispatch"
        assert result["session_log_path"] is not None
        assert Path(result["session_log_path"]).exists()
        assert result["duration_seconds"] > 0
