"""Tier 2 write tool: dispatch a headless Claude Code session.

Spawns ``claude -p <prompt>`` as a subprocess, waits for completion,
and returns the session ID for follow-up reads.

Constitutional constraints enforced in this module:
- prompt is passed as a single argv element, never shell-interpolated
- repo is restricted to [a-zA-Z0-9_-] with hardcoded /home/ilyac/code/ prefix
- model is a closed enum (sonnet, opus, haiku)
- No additional parameters influence subprocess argv, env, cwd, or stdin
- One call = one subprocess, no chaining, no retry on failure
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .audit import AuditLog

logger = logging.getLogger(__name__)

_REPO_BASE = Path("/home/ilyac/code")
_REPO_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_VALID_MODELS = frozenset({"sonnet", "opus", "haiku"})
_MAX_PROMPT_LEN = 50_000
_MIN_TIMEOUT = 30
_MAX_TIMEOUT = 1800
_DEFAULT_TIMEOUT = 600
_DEFAULT_MODEL = "sonnet"


def _validate_repo(repo: str) -> Path:
    """Validate repo name and return the resolved directory path.

    Rejects any name containing characters outside [a-zA-Z0-9_-].
    Resolves against the hardcoded prefix /home/ilyac/code/.
    """
    if not _REPO_NAME_RE.match(repo):
        raise ValueError(
            f"Invalid repo name '{repo}': must match [a-zA-Z0-9_-]. "
            "Path traversal and special characters are blocked."
        )
    repo_path = _REPO_BASE / repo
    if not repo_path.is_dir():
        raise ValueError(
            f"Repo directory not found: {repo_path}. "
            "Must be an existing directory under /home/ilyac/code/."
        )
    return repo_path


def _validate_prompt(prompt: str) -> str:
    """Validate prompt is non-empty and within size limits."""
    if not prompt:
        raise ValueError("Prompt must be a non-empty string.")
    if len(prompt) > _MAX_PROMPT_LEN:
        raise ValueError(
            f"Prompt too long: {len(prompt)} chars (max {_MAX_PROMPT_LEN})."
        )
    return prompt


def _validate_model(model: str | None) -> str:
    """Validate and return the model, defaulting to sonnet."""
    if model is None:
        return _DEFAULT_MODEL
    if model not in _VALID_MODELS:
        raise ValueError(
            f"Invalid model '{model}': must be one of {sorted(_VALID_MODELS)}."
        )
    return model


def _validate_timeout(timeout_seconds: int) -> tuple[int, list[str]]:
    """Validate and clamp timeout to [30, 1800]. Returns (clamped_value, warnings)."""
    warnings: list[str] = []
    if timeout_seconds < _MIN_TIMEOUT:
        warnings.append(
            f"timeout_seconds {timeout_seconds} clamped to minimum {_MIN_TIMEOUT}"
        )
        timeout_seconds = _MIN_TIMEOUT
    elif timeout_seconds > _MAX_TIMEOUT:
        warnings.append(
            f"timeout_seconds {timeout_seconds} clamped to maximum {_MAX_TIMEOUT}"
        )
        timeout_seconds = _MAX_TIMEOUT
    return timeout_seconds, warnings


def _find_session_log(repo: str, start_time: float) -> tuple[str | None, str | None]:
    """Find the session log file created by the dispatched CC subprocess.

    CC writes session logs to ~/.claude/projects/<encoded-cwd>/<session-id>.jsonl.
    The encoded cwd for /home/ilyac/code/<repo> is -home-ilyac-code-<repo>.

    Returns (session_id, session_log_path) or (None, None).
    """
    encoded_cwd = f"-home-ilyac-code-{repo}"
    sessions_dir = Path.home() / ".claude" / "projects" / encoded_cwd

    if not sessions_dir.is_dir():
        return None, None

    candidates = [
        p for p in sessions_dir.glob("*.jsonl")
        if p.stat().st_mtime >= start_time
    ]

    if not candidates:
        return None, None

    best = max(candidates, key=lambda p: p.stat().st_mtime)
    return best.stem, str(best)


def run_dispatch(
    prompt: str,
    repo: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
    model: str | None = None,
    audit_log: AuditLog | None = None,
) -> dict[str, Any]:
    """Execute a headless Claude Code dispatch.

    Validates inputs, spawns ``claude -p <prompt>`` as a subprocess,
    waits for completion, finds the resulting session log, and returns
    a structured result dict.

    The audit_log parameter is for the tool-level completion entry.
    Middleware handles the call-level entry/completion logging separately.
    """
    warnings: list[str] = []

    # --- Validate ---
    repo_path = _validate_repo(repo)
    prompt = _validate_prompt(prompt)
    model_str = _validate_model(model)
    timeout_seconds, timeout_warnings = _validate_timeout(timeout_seconds)
    warnings.extend(timeout_warnings)

    # --- Build argv (list form only, never shell=True) ---
    args = ["claude", "-p", prompt, "--model", model_str]

    start_time = time.time()
    timed_out = False
    stdout_data = ""
    stderr_data = ""
    exit_code = -1

    try:
        proc = subprocess.Popen(
            args,
            cwd=str(repo_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout_seconds)
            stdout_data = stdout_bytes.decode("utf-8", errors="replace")
            stderr_data = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.terminate()  # SIGTERM
            try:
                stdout_bytes, stderr_bytes = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()  # SIGKILL
                stdout_bytes, stderr_bytes = proc.communicate()
            stdout_data = stdout_bytes.decode("utf-8", errors="replace")
            stderr_data = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = proc.returncode if proc.returncode is not None else -1

    except FileNotFoundError:
        duration = round(time.time() - start_time, 2)
        error_msg = "claude binary not found on PATH"
        result: dict[str, Any] = {
            "session_id": None,
            "exit_code": -1,
            "duration_seconds": duration,
            "timed_out": False,
            "stdout_tail": "",
            "stderr_tail": (
                "claude binary not found on PATH. "
                "Install Claude Code CLI."
            ),
            "session_log_path": None,
            "warnings": [error_msg],
        }
        if audit_log:
            audit_log.log(
                operation="dispatch_cc_session:completed",
                mode="n/a",
                success=False,
                details={
                    "repo": repo,
                    "exit_code": -1,
                    "duration_seconds": duration,
                    "timed_out": False,
                    "session_id": None,
                },
                error=error_msg,
            )
        return result

    duration = round(time.time() - start_time, 2)

    # --- Find session log ---
    session_id, session_log_path = _find_session_log(repo, start_time)
    if session_id is None:
        time.sleep(2)
        session_id, session_log_path = _find_session_log(repo, start_time)

    result = {
        "session_id": session_id,
        "exit_code": exit_code,
        "duration_seconds": duration,
        "timed_out": timed_out,
        "stdout_tail": stdout_data[-2000:] if stdout_data else "",
        "stderr_tail": stderr_data[-2000:] if stderr_data else "",
        "session_log_path": session_log_path,
        "warnings": warnings,
    }

    # --- Audit completion (no prompt content) ---
    if audit_log:
        audit_log.log(
            operation="dispatch_cc_session:completed",
            mode="n/a",
            success=exit_code == 0 and not timed_out,
            details={
                "repo": repo,
                "exit_code": exit_code,
                "duration_seconds": duration,
                "timed_out": timed_out,
                "session_id": session_id,
            },
        )

    return result
