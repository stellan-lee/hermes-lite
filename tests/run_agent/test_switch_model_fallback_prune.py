"""Regression coverage for fallback pruning after an explicit model switch."""

from unittest.mock import MagicMock, patch

from run_agent import AIAgent


def _make_agent(chain):
    agent = AIAgent.__new__(AIAgent)
    agent.provider = "openai-codex"
    agent.model = "gpt-5.4"
    agent.base_url = "https://chatgpt.com/backend-api/codex"
    agent.api_key = "codex-key"
    agent.api_mode = "codex_responses"
    agent.client = MagicMock()
    agent._client_kwargs = {"api_key": "codex-key", "base_url": agent.base_url}
    agent.context_compressor = None
    agent._cached_system_prompt = "cached"
    agent._primary_runtime = {}
    agent._fallback_activated = False
    agent._fallback_index = 0
    agent._fallback_chain = list(chain)
    agent._config_context_length = None
    agent._transport_cache = {}
    agent._create_openai_client = lambda *_a, **_kw: MagicMock()
    return agent


def _switch_to_custom(agent):
    with patch("hermes_cli.timeouts.get_provider_request_timeout", return_value=None):
        agent.switch_model(
            new_model="local-model",
            new_provider="custom",
            api_key="local-key",
            base_url="http://localhost:1234/v1",
            api_mode="chat_completions",
        )


def test_switch_drops_old_and_new_primary_from_fallback_chain():
    agent = _make_agent([
        {"provider": "openai-codex", "model": "gpt-5.4"},
        {"provider": "custom", "model": "local-model"},
        {"provider": "custom", "model": "backup-model"},
    ])

    _switch_to_custom(agent)

    assert agent._fallback_chain == []


def test_switch_with_empty_chain_stays_empty():
    agent = _make_agent([])
    _switch_to_custom(agent)
    assert agent._fallback_chain == []


def test_switch_initializes_missing_fallback_attrs():
    agent = _make_agent([])
    del agent._fallback_chain
    _switch_to_custom(agent)
    assert agent._fallback_chain == []


def test_switch_within_same_provider_preserves_chain():
    chain = [{"provider": "openai-codex", "model": "gpt-5.3-codex"}]
    agent = _make_agent(chain)

    with patch("hermes_cli.timeouts.get_provider_request_timeout", return_value=None):
        agent.switch_model(
            new_model="gpt-5.3-codex",
            new_provider="openai-codex",
            api_key="codex-key",
            base_url="https://chatgpt.com/backend-api/codex",
            api_mode="codex_responses",
        )

    assert agent._fallback_chain == chain
