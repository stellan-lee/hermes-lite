"""API-mode selection for retained Codex and compatible endpoints."""

from marlow_cli.providers import determine_api_mode


def test_codex_provider_uses_responses():
    assert determine_api_mode("openai-codex") == "codex_responses"


def test_codex_alias_uses_responses():
    assert determine_api_mode("codex") == "codex_responses"


def test_custom_endpoint_uses_chat_completions():
    assert determine_api_mode("custom", "http://localhost:1234/v1") == "chat_completions"


def test_unknown_compatible_endpoint_uses_chat_completions():
    assert determine_api_mode("my-provider", "https://llm.example/v1") == "chat_completions"
