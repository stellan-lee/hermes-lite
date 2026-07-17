from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from run_agent import AgentError, AIAgent


def message(content="", tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def response(content="", tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=message(content, tool_calls))])


def tool_call(name, arguments, identifier="call-1"):
    return SimpleNamespace(
        id=identifier,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def test_chat_returns_final_text_without_tools(tmp_path):
    client = FakeClient([response("hello")])
    agent = AIAgent("model", client=client, workspace=str(tmp_path))
    assert agent.chat("hi") == "hello"
    request = client.chat.completions.requests[0]
    assert request["model"] == "model"
    assert request["messages"][-1] == {"role": "user", "content": "hi"}
    assert len(request["tools"]) == 5


def test_agent_executes_tool_and_returns_complete_trajectory(tmp_path):
    (tmp_path / "note.txt").write_text("content", encoding="utf-8")
    client = FakeClient(
        [
            response(tool_calls=[tool_call("read_file", '{"path":"note.txt"}')]),
            response("The file says content."),
        ]
    )
    agent = AIAgent("model", client=client, workspace=str(tmp_path))
    result = agent.run_conversation("Read note.txt")
    assert result["final_response"] == "The file says content."
    assert result["tool_rounds"] == 1
    tool_message = next(item for item in result["messages"] if item["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert payload["success"] is True
    assert payload["content"] == "content"
    assert client.chat.completions.requests[1]["messages"][-1] == tool_message


def test_invalid_tool_json_becomes_a_tool_result(tmp_path):
    client = FakeClient(
        [
            response(tool_calls=[tool_call("read_file", "{")]),
            response("recovered"),
        ]
    )
    result = AIAgent("model", client=client, workspace=str(tmp_path)).run_conversation("go")
    payload = json.loads(next(m for m in result["messages"] if m["role"] == "tool")["content"])
    assert payload["success"] is False
    assert "invalid tool arguments" in payload["error"]


def test_zero_tool_iterations_omits_tools_and_rejects_unexpected_call(tmp_path):
    client = FakeClient([response(tool_calls=[tool_call("read_file", "{}")])])
    agent = AIAgent("model", client=client, workspace=str(tmp_path), max_iterations=0)
    with pytest.raises(AgentError, match="after the tool iteration limit"):
        agent.run_conversation("go")
    assert "tools" not in client.chat.completions.requests[0]


def test_history_is_preserved_but_external_system_messages_are_replaced(tmp_path):
    client = FakeClient([response("done")])
    agent = AIAgent("model", client=client, workspace=str(tmp_path))
    agent.run_conversation(
        "new",
        system_message="active",
        conversation_history=[
            {"role": "system", "content": "stale"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "reply"},
        ],
    )
    messages = client.chat.completions.requests[0]["messages"]
    assert messages[0] == {"role": "system", "content": "active"}
    assert all(item.get("content") != "stale" for item in messages)


def test_model_errors_are_wrapped(tmp_path):
    agent = AIAgent("model", client=FakeClient([RuntimeError("offline")]), workspace=str(tmp_path))
    with pytest.raises(AgentError, match="model request failed: offline"):
        agent.chat("hi")


@pytest.mark.parametrize("model", ["", "   "])
def test_model_is_required(model):
    with pytest.raises(ValueError, match="model must be"):
        AIAgent(model, client=FakeClient([]))


def test_boolean_temperature_is_rejected():
    with pytest.raises(ValueError, match="temperature must be"):
        AIAgent("model", client=FakeClient([]), temperature=True)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"temperature": 3}, "between 0 and 2"),
        ({"max_iterations": True}, "non-negative integer"),
        ({"system_prompt": None}, "system_prompt must be a string"),
    ],
)
def test_direct_api_validates_runtime_options(kwargs, message):
    with pytest.raises(ValueError, match=message):
        AIAgent("model", client=FakeClient([]), **kwargs)


def test_system_message_must_be_text(tmp_path):
    agent = AIAgent("model", client=FakeClient([]), workspace=str(tmp_path))
    with pytest.raises(ValueError, match="system_message must be"):
        agent.run_conversation("hello", system_message=3)
