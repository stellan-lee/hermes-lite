"""Hermes Lite's synchronous OpenAI-compatible agent loop."""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

from model_tools import DEFAULT_TOOL_NAMES, ToolRuntime
from tools.registry import ApprovalCallback

DEFAULT_SYSTEM_PROMPT = """You are Hermes Lite, a careful local coding agent.
Use tools only when they materially help. Read before editing, keep changes
small, explain failures plainly, and never claim a command or edit succeeded
unless its tool result says it did."""


class AgentError(RuntimeError):
    """A model-client or conversation-loop failure."""


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
        pieces: list[str] = []
        for part in content:
            text = _get(part, "text")
            if isinstance(text, str):
                pieces.append(text)
        return "".join(pieces)
    return str(content)


def _normalise_tool_call(tool_call: Any, fallback_index: int) -> dict[str, Any]:
    function = _get(tool_call, "function", {})
    name = _get(function, "name", "")
    arguments = _get(function, "arguments", "{}")
    identifier = _get(tool_call, "id") or f"call_{fallback_index}"
    if not isinstance(name, str) or not name:
        raise AgentError("model returned a tool call without a function name")
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments)
    return {
        "id": str(identifier),
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _normalise_history(history: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for raw in history or ():
        if not isinstance(raw, Mapping):
            raise ValueError("conversation_history entries must be mappings")
        role = raw.get("role")
        if role == "system":
            continue
        if role not in {"user", "assistant", "tool"}:
            raise ValueError(f"unsupported history role: {role}")
        message = dict(raw)
        message["role"] = role
        messages.append(message)
    return messages


class AIAgent:
    """A small, embeddable tool-calling agent.

    The client may be injected for tests or custom transports. Otherwise the
    official OpenAI client is created against any OpenAI-compatible base URL.
    """

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_iterations: int = 20,
        temperature: float | None = 0.2,
        enabled_tools: Sequence[str] | None = DEFAULT_TOOL_NAMES,
        workspace: str = ".",
        terminal_enabled: bool = False,
        terminal_confirm: bool = True,
        terminal_timeout_seconds: int = 60,
        approval_callback: ApprovalCallback | None = None,
        client: Any | None = None,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        if (
            isinstance(max_iterations, bool)
            or not isinstance(max_iterations, int)
            or max_iterations < 0
        ):
            raise ValueError("max_iterations must be a non-negative integer")
        if temperature is not None and (
            isinstance(temperature, bool) or not isinstance(temperature, int | float)
        ):
            raise ValueError("temperature must be a number or null")
        if temperature is not None and not 0 <= float(temperature) <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if not isinstance(system_prompt, str):
            raise ValueError("system_prompt must be a string")

        self.model = model.strip()
        self.system_prompt = system_prompt.strip() or DEFAULT_SYSTEM_PROMPT
        self.max_iterations = max_iterations
        self.temperature = float(temperature) if temperature is not None else None
        self.tool_runtime = ToolRuntime(
            workspace=workspace,
            enabled_tools=enabled_tools,
            terminal_enabled=terminal_enabled,
            terminal_confirm=terminal_confirm,
            terminal_timeout_seconds=terminal_timeout_seconds,
            approval_callback=approval_callback,
        )

        if client is not None:
            self.client = client
        else:
            resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
            if not resolved_key:
                raise ValueError("api_key is required when no client is injected")
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - packaging guarantees it.
                raise AgentError("the openai package is not installed") from exc
            kwargs: dict[str, Any] = {"api_key": resolved_key}
            if base_url:
                kwargs["base_url"] = base_url
            self.client = OpenAI(**kwargs)

    def chat(self, message: str) -> str:
        """Return only the final response for one independent user message."""

        return self.run_conversation(message)["final_response"]

    def run_conversation(
        self,
        user_message: str,
        system_message: str | None = None,
        conversation_history: Sequence[Mapping[str, Any]] | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Run one turn and return the final response plus OpenAI-format messages."""

        del task_id
        if not isinstance(user_message, str) or not user_message.strip():
            raise ValueError("user_message must be a non-empty string")

        if system_message is not None and not isinstance(system_message, str):
            raise ValueError("system_message must be a string or null")
        active_system_prompt = (system_message or self.system_prompt).strip()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": active_system_prompt},
            *_normalise_history(conversation_history),
            {"role": "user", "content": user_message},
        ]
        tool_rounds = 0

        while True:
            schemas = self.tool_runtime.schemas() if tool_rounds < self.max_iterations else []
            request: dict[str, Any] = {
                "model": self.model,
                "messages": copy.deepcopy(messages),
            }
            if schemas:
                request["tools"] = schemas
                request["tool_choice"] = "auto"
            if self.temperature is not None:
                request["temperature"] = self.temperature

            try:
                response = self.client.chat.completions.create(**request)
                choices = _get(response, "choices", [])
                if not choices:
                    raise AgentError("model returned no choices")
                response_message = _get(choices[0], "message")
                if response_message is None:
                    raise AgentError("model returned a choice without a message")
            except AgentError:
                raise
            except Exception as exc:
                raise AgentError(f"model request failed: {exc}") from exc

            content = _content_text(_get(response_message, "content"))
            raw_tool_calls = _get(response_message, "tool_calls") or []
            tool_calls = [
                _normalise_tool_call(tool_call, index)
                for index, tool_call in enumerate(raw_tool_calls, 1)
            ]
            assistant_message: dict[str, Any] = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            messages.append(assistant_message)

            if not tool_calls:
                return {
                    "final_response": content,
                    "messages": messages,
                    "tool_rounds": tool_rounds,
                    "stop_reason": "complete",
                }

            if tool_rounds >= self.max_iterations:
                raise AgentError("model attempted a tool call after the tool iteration limit")

            for tool_call in tool_calls:
                function = tool_call["function"]
                try:
                    arguments = json.loads(function["arguments"] or "{}")
                except json.JSONDecodeError as exc:
                    result = json.dumps(
                        {"success": False, "error": f"invalid tool arguments: {exc.msg}"}
                    )
                else:
                    if not isinstance(arguments, dict):
                        result = json.dumps(
                            {"success": False, "error": "tool arguments must be an object"}
                        )
                    else:
                        result = self.tool_runtime.execute(function["name"], arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "name": function["name"],
                        "content": result,
                    }
                )
            tool_rounds += 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run the shared Hermes Lite command-line interface."""

    from hermes_cli.main import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
