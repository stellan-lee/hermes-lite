"""Tests for context token tracking in run_agent.py's usage extraction.

The context counter (status bar) must show the prompt tokens reported by
retained transports. This is an integration test for token extraction in
run_conversation(), not the ContextCompressor itself (which
is tested in tests/agent/test_context_compressor.py).
"""

import sys
import types
from types import SimpleNamespace

sys.modules.setdefault("fire", types.SimpleNamespace(Fire=lambda *a, **k: None))

import run_agent


def _patch_bootstrap(monkeypatch):
    monkeypatch.setattr(run_agent, "get_tool_definitions", lambda **kwargs: [{
        "type": "function",
        "function": {"name": "t", "description": "t", "parameters": {"type": "object", "properties": {}}},
    }])
    monkeypatch.setattr(run_agent, "check_toolset_requirements", lambda: {})


class _FakeOpenAIClient:
    """Fake OpenAI client returned by mocked resolve_provider_client."""
    api_key = "fake-codex-key"
    base_url = "https://api.openai.com/v1"
    _default_headers = None


def _make_agent(monkeypatch, api_mode, provider, response_fn):
    _patch_bootstrap(monkeypatch)
    if provider == "openai-codex":
        monkeypatch.setattr(
            "agent.auxiliary_client.resolve_provider_client",
            lambda *a, **kw: (_FakeOpenAIClient(), "test-model"),
        )

    class _A(run_agent.AIAgent):
        def __init__(self, *a, **kw):
            kw.update(skip_context_files=True, skip_memory=True, max_iterations=4)
            super().__init__(*a, **kw)
            self._cleanup_task_resources = self._persist_session = lambda *a, **k: None
            self._save_trajectory = lambda *a, **k: None

        def run_conversation(self, msg, conversation_history=None, task_id=None):
            self._interruptible_api_call = lambda kw: response_fn()
            self._disable_streaming = True
            return super().run_conversation(msg, conversation_history=conversation_history, task_id=task_id)

    return _A(model="test-model", api_key="test-key", base_url="http://localhost:1234/v1", provider=provider, api_mode=api_mode)


# -- Compatible chat: prompt_tokens already total --

def test_openai_prompt_tokens_unchanged(monkeypatch):
    resp = lambda: SimpleNamespace(
        choices=[SimpleNamespace(index=0, message=SimpleNamespace(
            role="assistant", content="ok", tool_calls=None, reasoning_content=None,
        ), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=5000, completion_tokens=100, total_tokens=5100),
        model="gpt-4o",
    )
    agent = _make_agent(monkeypatch, "chat_completions", "custom", resp)
    agent.run_conversation("hi")
    assert agent.context_compressor.last_prompt_tokens == 5000


# -- Codex: no cache fields, getattr returns 0 --

def test_codex_no_cache_fields(monkeypatch):
    resp = lambda: SimpleNamespace(
        output=[SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text="ok")])],
        usage=SimpleNamespace(input_tokens=3000, output_tokens=50, total_tokens=3050),
        status="completed", model="gpt-5-codex",
    )
    agent = _make_agent(monkeypatch, "codex_responses", "openai-codex", resp)
    agent.run_conversation("hi")
    assert agent.context_compressor.last_prompt_tokens == 3000
