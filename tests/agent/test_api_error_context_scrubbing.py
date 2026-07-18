"""Regression coverage for wire-only context echoed by API errors."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.agent_runtime_helpers import (
    dump_api_request_debug,
    extract_api_error_context,
    format_exception_traceback_for_log,
    sanitize_api_error_text,
)
from agent.stream_diag import flatten_exception_chain
from run_agent import AIAgent


PRIVATE = "private lesson must remain wire-only"
WORK_BLOCK = (
    "<work-experience-context>" + PRIVATE + "</work-experience-context>"
)
MEMORY_BLOCK = "<memory-context>private memory</memory-context>"


class EchoingAPIError(RuntimeError):
    status_code = 400

    def __init__(self) -> None:
        super().__init__(f"invalid request {WORK_BLOCK} visible suffix")
        self.body = {
            "error": {
                "message": f"bad field {WORK_BLOCK} body suffix",
                "metadata": {"nested": MEMORY_BLOCK},
            }
        }
        self.response = SimpleNamespace(
            status_code=400,
            text=f"response prefix {MEMORY_BLOCK} response suffix",
            headers={},
        )


def _assert_private_context_absent(value) -> None:
    serialized = json.dumps(value, default=str)
    assert PRIVATE not in serialized
    assert "private memory" not in serialized
    assert "work-experience-context" not in serialized.lower()
    assert "memory-context" not in serialized.lower()


def test_sanitize_api_error_text_handles_literal_json_and_html_escaped_blocks():
    samples = (
        f"before {WORK_BLOCK} after",
        (
            r"before \u003cwork-experience-context\u003e"
            + PRIVATE
            + r"\u003c/work-experience-context\u003e after"
        ),
        (
            "before &lt;memory-context&gt;private memory"
            "&lt;/memory-context&gt; after"
        ),
    )

    for sample in samples:
        safe = sanitize_api_error_text(sample)
        _assert_private_context_absent(safe)
        assert "before" in safe
        assert "after" in safe


def test_error_context_is_sanitized_without_mutating_raw_exception():
    error = EchoingAPIError()

    context = extract_api_error_context(error)

    assert PRIVATE in str(error)
    assert PRIVATE in error.body["error"]["message"]
    _assert_private_context_absent(context)
    assert "body suffix" in context["message"]


def test_summary_cleaner_traceback_and_exception_chain_are_safe():
    error = EchoingAPIError()
    inner = RuntimeError(f"inner {MEMORY_BLOCK} visible inner suffix")
    error.__cause__ = inner
    agent_stub = object.__new__(AIAgent)

    values = (
        AIAgent._summarize_api_error(error),
        agent_stub._clean_error_message(str(error)),
        format_exception_traceback_for_log(error),
        flatten_exception_chain(error),
    )

    for value in values:
        _assert_private_context_absent(value)
    assert "body suffix" in values[0]
    assert "visible suffix" in values[1]
    assert "visible inner suffix" in values[2]
    assert "visible inner suffix" in values[3]


def test_debug_dump_scrubs_error_message_body_response_and_request(tmp_path):
    error = EchoingAPIError()
    agent = SimpleNamespace(
        client=SimpleNamespace(api_key="test-key"),
        session_id="session-safe",
        base_url="https://example.invalid/v1",
        api_mode="chat_completions",
        logs_dir=tmp_path,
        verbose_logging=False,
        log_prefix="",
        _mask_api_key_for_logs=lambda _key: "***",
        _vprint=lambda *_args, **_kwargs: None,
    )
    kwargs = {
        "model": "test-model",
        "messages": [
            {"role": "user", "content": f"question {WORK_BLOCK}"},
        ],
    }

    dump_file = dump_api_request_debug(
        agent,
        kwargs,
        reason="non_retryable_client_error",
        error=error,
    )

    assert dump_file is not None
    payload = json.loads(dump_file.read_text(encoding="utf-8"))
    _assert_private_context_absent(payload)
    assert "body suffix" in payload["error"]["body"]["error"]["message"]
    assert "response suffix" in payload["error"]["response_text"]


def test_non_retryable_api_error_is_safe_in_logs_status_dump_and_result(
    monkeypatch,
    tmp_path,
    caplog,
):
    """Raw exception remains classifiable while every outward copy is scrubbed."""

    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        agent = AIAgent(
            api_key="test-key-1234567890",
            base_url="https://example.invalid/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )

    error = EchoingAPIError()
    agent.client = MagicMock()
    agent.client.chat.completions.create.side_effect = error
    agent.logs_dir = tmp_path
    monkeypatch.setattr(agent, "_persist_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent, "_has_pending_fallback", lambda: False)
    captured: list[str] = []
    monkeypatch.setattr(
        agent,
        "_buffer_vprint",
        lambda message, **_kwargs: captured.append(str(message)),
    )
    monkeypatch.setattr(
        agent,
        "_emit_status",
        lambda message, **_kwargs: captured.append(str(message)),
    )
    monkeypatch.setattr(
        agent,
        "_vprint",
        lambda message, **_kwargs: captured.append(str(message)),
    )
    hooks: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "marlow_cli.plugins.invoke_hook",
        lambda name, **kwargs: hooks.append((name, kwargs)) or [],
    )

    with caplog.at_level(logging.DEBUG):
        result = agent.run_conversation("hello")

    _assert_private_context_absent(result)
    _assert_private_context_absent(captured)
    _assert_private_context_absent([record.getMessage() for record in caplog.records])
    _assert_private_context_absent(hooks)
    dumps = list(tmp_path.glob("request_dump_*.json"))
    assert dumps
    _assert_private_context_absent(json.loads(dumps[-1].read_text(encoding="utf-8")))
    assert result["failed"] is True
    assert "body suffix" in result["error"]
