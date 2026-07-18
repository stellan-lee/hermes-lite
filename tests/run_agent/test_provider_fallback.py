"""Tests for retained ordered fallback chains."""

from unittest.mock import MagicMock, patch

from run_agent import AIAgent


def _make_agent(fallback_model=None):
    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        agent = AIAgent(
            api_key="local-key",
            base_url="http://127.0.0.1:1234/v1",
            provider="custom",
            model="primary-model",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            fallback_model=fallback_model,
        )
        agent.client = MagicMock()
        return agent


def _mock_client(base_url="http://127.0.0.1:4321/v1", api_key="fallback-key"):
    client = MagicMock()
    client.base_url = base_url
    client.api_key = api_key
    return client


def test_no_fallback_chain():
    agent = _make_agent()
    assert agent._fallback_chain == []
    assert agent._try_activate_fallback() is False


def test_invalid_entries_are_filtered():
    agent = _make_agent([
        {"provider": "custom", "model": "fallback-model"},
        {"provider": "", "model": "missing-provider"},
        {"provider": "custom"},
        "not-a-dict",
    ])
    assert agent._fallback_chain == [
        {"provider": "custom", "model": "fallback-model"}
    ]


def test_chain_advances_across_custom_endpoints():
    fallbacks = [
        {"provider": "local-a", "model": "model-a"},
        {"provider": "local-b", "model": "model-b"},
    ]
    agent = _make_agent(fallbacks)
    with patch(
        "agent.auxiliary_client.resolve_provider_client",
        return_value=(_mock_client(), "resolved"),
    ):
        assert agent._try_activate_fallback() is True
        assert agent.model == "model-a"
        assert agent._try_activate_fallback() is True
        assert agent.model == "model-b"
        assert agent._try_activate_fallback() is False


def test_unconfigured_entry_is_skipped():
    agent = _make_agent([
        {"provider": "broken", "model": "missing"},
        {"provider": "custom", "model": "fallback-model"},
    ])
    with patch("agent.auxiliary_client.resolve_provider_client") as resolve:
        resolve.side_effect = [
            (None, None),
            (_mock_client(), "fallback-model"),
        ]
        assert agent._try_activate_fallback() is True
        assert agent.model == "fallback-model"


def test_key_env_is_forwarded_to_custom_fallback(monkeypatch):
    monkeypatch.setenv("LOCAL_FALLBACK_KEY", "secret")
    agent = _make_agent([{
        "provider": "custom",
        "model": "fallback-model",
        "base_url": "https://fallback.example/v1",
        "key_env": "LOCAL_FALLBACK_KEY",
    }])
    with patch(
        "agent.auxiliary_client.resolve_provider_client",
        return_value=(_mock_client("https://fallback.example/v1", "secret"), "fallback-model"),
    ) as resolve:
        assert agent._try_activate_fallback() is True
        assert resolve.call_args.kwargs["explicit_api_key"] == "secret"


def test_same_backend_entry_is_skipped():
    agent = _make_agent([
        {
            "provider": "custom-alias",
            "model": "primary-model",
            "base_url": "http://127.0.0.1:1234/v1",
        },
        {
            "provider": "custom",
            "model": "fallback-model",
            "base_url": "http://127.0.0.1:4321/v1",
        },
    ])
    with patch(
        "agent.auxiliary_client.resolve_provider_client",
        return_value=(_mock_client(), "fallback-model"),
    ) as resolve:
        assert agent._try_activate_fallback() is True
        assert resolve.call_args.args[0] == "custom"
