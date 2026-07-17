"""Explicit registry for the fixed Hermes Lite tool set."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ToolHandler = Callable[[Mapping[str, Any], "ToolContext"], str]
ApprovalCallback = Callable[[str], bool]


@dataclass(slots=True)
class ToolContext:
    """Runtime limits shared by all tool handlers."""

    workspace: Path
    terminal_enabled: bool = False
    terminal_confirm: bool = True
    terminal_timeout_seconds: int = 60
    approval_callback: ApprovalCallback | None = None

    def __post_init__(self) -> None:
        self.workspace = self.workspace.expanduser().resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"workspace is not a directory: {self.workspace}")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """A tool schema and its JSON-string handler."""

    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: ToolHandler

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters),
            },
        }


class ToolRegistry:
    """A deliberately non-discovering tool registry."""

    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"tool already registered: {definition.name}")
        self._definitions[definition.name] = definition

    def names(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def schemas(self, enabled: set[str] | None = None) -> list[dict[str, Any]]:
        selected = enabled if enabled is not None else set(self._definitions)
        return [
            definition.openai_schema()
            for name, definition in self._definitions.items()
            if name in selected
        ]

    def execute(self, name: str, arguments: Mapping[str, Any], context: ToolContext) -> str:
        definition = self._definitions.get(name)
        if definition is None:
            return error_result(f"unknown tool: {name}")
        try:
            result = definition.handler(arguments, context)
            if not isinstance(result, str):
                raise TypeError(f"tool {name} returned {type(result).__name__}, expected str")
            json.loads(result)
            return result
        except Exception as exc:  # Tool errors are data, not agent-loop crashes.
            return error_result(str(exc))


def success_result(**payload: Any) -> str:
    return json.dumps({"success": True, **payload}, ensure_ascii=False)


def error_result(message: str, **payload: Any) -> str:
    return json.dumps({"success": False, "error": message, **payload}, ensure_ascii=False)


registry = ToolRegistry()
