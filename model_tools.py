"""Tool schemas and dispatch for the fixed Hermes Lite tool set."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tools import ToolContext, registry
from tools.registry import ApprovalCallback, error_result

DEFAULT_TOOL_NAMES: tuple[str, ...] = (
    "read_file",
    "write_file",
    "patch",
    "search_files",
    "terminal",
)


class ToolRuntime:
    """Per-agent tool selection and security context."""

    def __init__(
        self,
        *,
        workspace: str | Path = ".",
        enabled_tools: Sequence[str] | None = None,
        terminal_enabled: bool = False,
        terminal_confirm: bool = True,
        terminal_timeout_seconds: int = 60,
        approval_callback: ApprovalCallback | None = None,
    ) -> None:
        selected = tuple(enabled_tools) if enabled_tools is not None else DEFAULT_TOOL_NAMES
        unknown = sorted(set(selected) - set(registry.names()))
        if unknown:
            raise ValueError(f"unknown enabled tools: {', '.join(unknown)}")
        if not isinstance(terminal_enabled, bool) or not isinstance(terminal_confirm, bool):
            raise ValueError("terminal_enabled and terminal_confirm must be booleans")
        if (
            isinstance(terminal_timeout_seconds, bool)
            or not isinstance(terminal_timeout_seconds, int)
            or not 1 <= terminal_timeout_seconds <= 300
        ):
            raise ValueError("terminal_timeout_seconds must be between 1 and 300")
        self.enabled_tools = set(selected)
        self.context = ToolContext(
            workspace=Path(workspace),
            terminal_enabled=terminal_enabled,
            terminal_confirm=terminal_confirm,
            terminal_timeout_seconds=terminal_timeout_seconds,
            approval_callback=approval_callback,
        )

    def schemas(self) -> list[dict[str, Any]]:
        return registry.schemas(self.enabled_tools)

    def execute(self, name: str, arguments: Mapping[str, Any]) -> str:
        if name not in self.enabled_tools:
            return error_result(f"tool is disabled: {name}")
        return registry.execute(name, arguments, self.context)


def handle_function_call(
    function_name: str,
    arguments: str | Mapping[str, Any],
    task_id: str | None = None,
    *,
    runtime: ToolRuntime | None = None,
) -> str:
    """Parse and execute one model tool call.

    ``task_id`` remains accepted so existing embedders can upgrade without
    changing call sites; Lite has no background task subsystem.
    """

    del task_id
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments or "{}")
        except json.JSONDecodeError as exc:
            return error_result(f"invalid tool arguments: {exc.msg}")
    else:
        parsed = dict(arguments)
    if not isinstance(parsed, dict):
        return error_result("tool arguments must decode to an object")
    active_runtime = runtime or ToolRuntime(terminal_enabled=False)
    return active_runtime.execute(function_name, parsed)


def get_tool_schemas(runtime: ToolRuntime | None = None) -> list[dict[str, Any]]:
    """Return OpenAI-format tool schemas for an agent runtime."""

    return (runtime or ToolRuntime()).schemas()
