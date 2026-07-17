"""Confirmed, non-shell terminal execution."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tools.registry import ToolContext, ToolDefinition, error_result, registry, success_result

_MAX_OUTPUT_CHARS = 50_000
_SAFE_ENVIRONMENT_NAMES = {
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOGNAME",
    "PATH",
    "PATHEXT",
    "SHELL",
    "SYSTEMROOT",
    "TERM",
    "TMPDIR",
    "USER",
    "WINDIR",
}


def _coerce_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _truncate(value: str | bytes | None) -> tuple[str, bool]:
    value = _coerce_output(value)
    if len(value) <= _MAX_OUTPUT_CHARS:
        return value, False
    half = _MAX_OUTPUT_CHARS // 2
    return f"{value[:half]}\n... output truncated ...\n{value[-half:]}", True


def _working_directory(context: ToolContext, raw_path: Any) -> Path:
    if raw_path is None:
        return context.workspace
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("cwd must be a non-empty string")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = context.workspace / candidate
    candidate = candidate.resolve(strict=True)
    try:
        candidate.relative_to(context.workspace)
    except ValueError as exc:
        raise ValueError("cwd escapes workspace") from exc
    if not candidate.is_dir():
        raise ValueError("cwd is not a directory")
    return candidate


def _terminal(arguments: Mapping[str, Any], context: ToolContext) -> str:
    if not context.terminal_enabled:
        return error_result("terminal execution is disabled")

    argv = arguments.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(item, str) or not item for item in argv)
    ):
        return error_result("argv must be a non-empty array of non-empty strings")

    timeout = arguments.get("timeout_seconds", context.terminal_timeout_seconds)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        return error_result("timeout_seconds must be a positive integer")
    timeout = min(timeout, context.terminal_timeout_seconds, 300)
    cwd = _working_directory(context, arguments.get("cwd"))
    display = f"argv={json.dumps(argv, ensure_ascii=True)} cwd={json.dumps(str(cwd))}"

    if context.terminal_confirm:
        if context.approval_callback is None:
            return error_result("terminal command requires an approval callback", command=display)
        try:
            approved = bool(context.approval_callback(display))
        except Exception as exc:
            return error_result(f"terminal approval failed: {exc}", command=display)
        if not approved:
            return error_result("terminal command denied", command=display)

    environment = {
        name: value for name, value in os.environ.items() if name.upper() in _SAFE_ENVIRONMENT_NAMES
    }
    environment["PYTHONIOENCODING"] = "utf-8"

    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return error_result(f"command not found: {argv[0]}", command=display)
    except subprocess.TimeoutExpired as exc:
        stdout, stdout_truncated = _truncate(exc.stdout)
        stderr, stderr_truncated = _truncate(exc.stderr)
        return error_result(
            f"command timed out after {timeout} seconds",
            command=display,
            stdout=stdout,
            stderr=stderr,
            truncated=stdout_truncated or stderr_truncated,
        )

    stdout, stdout_truncated = _truncate(completed.stdout)
    stderr, stderr_truncated = _truncate(completed.stderr)
    payload = {
        "command": display,
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "truncated": stdout_truncated or stderr_truncated,
    }
    if completed.returncode != 0:
        return error_result(f"command exited with code {completed.returncode}", **payload)
    return success_result(**payload)


registry.register(
    ToolDefinition(
        name="terminal",
        description="Run an approved command without a shell inside the workspace.",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "argv": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                },
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300},
            },
            "required": ["argv"],
        },
        handler=_terminal,
    )
)
