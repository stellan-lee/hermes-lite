from types import SimpleNamespace

import pytest

from agent.codex_runtime import (
    _raise_stream_error,
    _StreamErrorEvent,
    run_codex_app_server_turn,
)


def test_stream_error_event_is_self_contained():
    with pytest.raises(_StreamErrorEvent) as captured:
        _raise_stream_error(
            {
                "type": "error",
                "message": "request rejected",
                "code": "invalid_request",
                "param": "model",
            }
        )

    error = captured.value
    assert error.code == "invalid_request"
    assert error.param == "model"
    assert error.body["error"]["message"] == "request rejected"


def test_app_server_turn_has_no_removed_memory_or_skill_hooks():
    class _Session:
        def run_turn(self, user_input):
            assert user_input == "hello"
            return SimpleNamespace(
                final_text="done",
                projected_messages=[{"role": "assistant", "content": "done"}],
                tool_iterations=0,
                interrupted=False,
                error=None,
                thread_id="thread-1",
                turn_id="turn-1",
                should_retire=False,
            )

    agent = SimpleNamespace(_codex_session=_Session())
    messages = [{"role": "user", "content": "hello"}]

    result = run_codex_app_server_turn(
        agent,
        user_message="hello",
        messages=messages,
    )

    assert result["final_response"] == "done"
    assert result["completed"] is True
    assert messages[-1] == {"role": "assistant", "content": "done"}
