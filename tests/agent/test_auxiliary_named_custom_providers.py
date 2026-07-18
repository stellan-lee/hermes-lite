"""Tests for named custom provider and 'main' alias resolution in auxiliary_client."""

from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Redirect MARLOW_HOME and clear module caches."""
    marlow_home = tmp_path / ".marlow"
    marlow_home.mkdir()
    monkeypatch.setenv("MARLOW_HOME", str(marlow_home))
    # Write a minimal config so load_config doesn't fail
    (marlow_home / "config.yaml").write_text("model:\n  default: test-model\n")


def _write_config(tmp_path, config_dict):
    """Write a config.yaml to the test MARLOW_HOME."""
    import yaml
    config_path = tmp_path / ".marlow" / "config.yaml"
    config_path.write_text(yaml.dump(config_dict))


class TestNormalizeVisionProvider:
    """_normalize_vision_provider should resolve 'main' to actual main provider."""

    def test_main_resolves_to_named_custom(self, tmp_path):
        _write_config(tmp_path, {
            "model": {"default": "my-model", "provider": "beans"},
            "providers": {"beans": {"base_url": "http://localhost/v1"}},
        })
        from agent.auxiliary_client import _normalize_vision_provider
        assert _normalize_vision_provider("main") == "beans"



    def test_main_falls_back_to_custom_when_no_provider(self, tmp_path):
        _write_config(tmp_path, {"model": {"default": "gpt-4o"}})
        from agent.auxiliary_client import _normalize_vision_provider
        assert _normalize_vision_provider("main") == "custom"


    def test_codex_alias_still_works(self):
        from agent.auxiliary_client import _normalize_vision_provider
        assert _normalize_vision_provider("codex") == "openai-codex"

    def test_auto_unchanged(self):
        from agent.auxiliary_client import _normalize_vision_provider
        assert _normalize_vision_provider("auto") == "auto"
        assert _normalize_vision_provider(None) == "auto"







class TestProvidersDictApiMode:
    """Named compatible providers reject unsupported API modes."""


    def test_providers_dict_invalid_api_mode_is_dropped(self, tmp_path):
        _write_config(tmp_path, {
            "providers": {
                "weird": {
                    "name": "weird",
                    "base_url": "https://example.test",
                    "api_mode": "bogus_nonsense",
                    "model": "x",
                },
            },
        })
        from marlow_cli.runtime_provider import _get_named_custom_provider
        entry = _get_named_custom_provider("weird")
        assert entry is not None
        assert "api_mode" not in entry

    def test_providers_dict_without_api_mode_is_unchanged(self, tmp_path):
        _write_config(tmp_path, {
            "providers": {
                "localchat": {
                    "name": "localchat",
                    "base_url": "http://127.0.0.1:1234/v1",
                    "api_key": "local-key",
                    "model": "llama-3",
                },
            },
        })
        from marlow_cli.runtime_provider import _get_named_custom_provider
        entry = _get_named_custom_provider("localchat")
        assert entry is not None
        assert "api_mode" not in entry



    def test_provider_without_api_mode_still_uses_openai(self, tmp_path):
        """Named providers that don't declare api_mode should still go
        through the plain OpenAI-wire path (no regression)."""
        _write_config(tmp_path, {
            "providers": {
                "localchat": {
                    "name": "localchat",
                    "base_url": "http://127.0.0.1:1234/v1",
                    "api_key": "local-key",
                    "model": "llama-3",
                },
            },
        })
        from agent.auxiliary_client import resolve_provider_client
        from openai import OpenAI, AsyncOpenAI
        sync_client, _ = resolve_provider_client("localchat", async_mode=False)
        # sync returns the raw OpenAI client
        assert isinstance(sync_client, OpenAI)
        async_client, _ = resolve_provider_client("localchat", async_mode=True)
        assert isinstance(async_client, AsyncOpenAI)
