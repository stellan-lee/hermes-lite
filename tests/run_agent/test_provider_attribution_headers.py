"""Client headers for retained Codex and custom-compatible endpoints."""

from unittest.mock import MagicMock, patch

from run_agent import AIAgent


def _custom_agent() -> AIAgent:
    return AIAgent(
        api_key="test-key",
        base_url="https://api.example.com/v1",
        model="example-model",
        provider="custom",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )


@patch("run_agent.OpenAI")
def test_chatgpt_base_url_applies_codex_headers(mock_openai):
    mock_openai.return_value = MagicMock()
    agent = _custom_agent()

    with patch(
        "agent.auxiliary_client._codex_cloudflare_headers",
        return_value={"ChatGPT-Account-Id": "account-123"},
    ):
        agent._apply_client_headers_for_base_url("https://chatgpt.com/backend-api/codex")

    assert agent._client_kwargs["default_headers"] == {
        "ChatGPT-Account-Id": "account-123"
    }


@patch("run_agent.OpenAI")
def test_custom_base_url_clears_codex_headers(mock_openai):
    mock_openai.return_value = MagicMock()
    agent = _custom_agent()
    agent._client_kwargs["default_headers"] = {"X-Stale": "yes"}

    agent._apply_client_headers_for_base_url("https://api.example.com/v1")

    assert "default_headers" not in agent._client_kwargs
