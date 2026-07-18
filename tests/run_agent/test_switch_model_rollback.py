"""Model switching restores retained runtime state when client rebuild fails."""

from unittest.mock import MagicMock, patch

import pytest

from run_agent import AIAgent


def _make_agent(*, provider="custom", model="local-a", api_mode="chat_completions"):
    agent = AIAgent.__new__(AIAgent)
    agent.provider = provider
    agent.model = model
    agent.base_url = (
        "https://chatgpt.com/backend-api/codex"
        if provider == "openai-codex"
        else "http://localhost:1234/v1"
    )
    agent.api_key = "original-key"
    agent.api_mode = api_mode
    agent.client = MagicMock(name="OriginalClient")
    agent._client_kwargs = {"api_key": agent.api_key, "base_url": agent.base_url}
    agent.context_compressor = None
    agent._cached_system_prompt = "cached"
    agent._primary_runtime = {}
    agent._fallback_activated = False
    agent._fallback_index = 0
    agent._fallback_chain = []
    agent._fallback_chain = []
    agent._config_context_length = None
    agent._transport_cache = {}
    return agent


@pytest.mark.parametrize(
    ("provider", "model", "api_mode"),
    [
        ("custom", "local-a", "chat_completions"),
        ("openai-codex", "gpt-5.4", "codex_responses"),
    ],
)
def test_client_rebuild_failure_rolls_back(provider, model, api_mode):
    agent = _make_agent(provider=provider, model=model, api_mode=api_mode)
    original = {
        "provider": agent.provider,
        "model": agent.model,
        "base_url": agent.base_url,
        "api_key": agent.api_key,
        "api_mode": agent.api_mode,
        "client": agent.client,
        "client_kwargs": dict(agent._client_kwargs),
    }

    def boom(*_a, **_kw):
        raise RuntimeError("simulated client build failure")

    agent._create_openai_client = boom
    with patch("marlow_cli.timeouts.get_provider_request_timeout", return_value=None):
        with pytest.raises(RuntimeError, match="simulated client build failure"):
            agent.switch_model(
                new_model="local-b",
                new_provider="custom",
                api_key="new-key",
                base_url="http://localhost:5678/v1",
                api_mode="chat_completions",
            )

    for key in ("provider", "model", "base_url", "api_key", "api_mode", "client"):
        assert getattr(agent, key) == original[key]
    assert agent._client_kwargs == original["client_kwargs"]


def test_successful_custom_switch_rebuilds_client():
    agent = _make_agent()
    new_client = MagicMock(name="NewClient")
    agent._create_openai_client = lambda *_a, **_kw: new_client

    with patch("marlow_cli.timeouts.get_provider_request_timeout", return_value=None):
        agent.switch_model(
            new_model="local-b",
            new_provider="custom",
            api_key="new-key",
            base_url="http://localhost:5678/v1",
            api_mode="chat_completions",
        )

    assert agent.model == "local-b"
    assert agent.provider == "custom"
    assert agent.api_key == "new-key"
    assert agent.client is new_client
