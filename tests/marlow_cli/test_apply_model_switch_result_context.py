"""The model picker displays context from the retained runtime resolver."""

from unittest.mock import patch

from marlow_cli.model_switch import ModelSwitchResult


class _StubCLI:
    agent = None
    model = ""
    provider = ""
    requested_provider = ""
    api_key = ""
    _explicit_api_key = ""
    base_url = ""
    _explicit_base_url = ""
    api_mode = ""
    _pending_model_switch_note = ""


def _run_display(monkeypatch, result):
    import cli as cli_mod

    captured: list[str] = []
    monkeypatch.setattr(cli_mod, "_cprint", lambda value, *a, **k: captured.append(str(value)))
    monkeypatch.setattr(cli_mod, "save_config_value", lambda *a, **k: None)
    cli_mod.MarlowCLI._apply_model_switch_result(_StubCLI(), result, False)
    return captured


def test_picker_path_uses_codex_context(monkeypatch):
    result = ModelSwitchResult(
        success=True,
        new_model="gpt-5.5",
        target_provider="openai-codex",
        provider_changed=True,
        base_url="https://chatgpt.com/backend-api/codex",
        api_mode="codex_responses",
        provider_label="OpenAI Codex",
    )
    with patch("agent.model_metadata.get_model_context_length", return_value=272_000):
        lines = _run_display(monkeypatch, result)
    assert any("Context: 272,000 tokens" in line for line in lines)


def test_picker_path_uses_custom_endpoint_context(monkeypatch):
    result = ModelSwitchResult(
        success=True,
        new_model="local-model",
        target_provider="custom",
        provider_changed=True,
        base_url="http://localhost:1234/v1",
        api_mode="chat_completions",
        provider_label="Custom endpoint",
    )
    with patch("agent.model_metadata.get_model_context_length", return_value=131_072):
        lines = _run_display(monkeypatch, result)
    assert any("Context: 131,072 tokens" in line for line in lines)
