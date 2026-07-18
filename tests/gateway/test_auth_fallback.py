"""Test that AuthError triggers fallback provider resolution (#7230)."""

from unittest.mock import patch

import pytest


class TestResolveRuntimeAgentKwargsAuthFallback:
    """_resolve_runtime_agent_kwargs should try fallback on AuthError."""

    def test_auth_error_tries_fallback(self, tmp_path, monkeypatch):
        """When primary provider raises AuthError, fallback is attempted."""
        from marlow_cli.auth import AuthError

        # Create a config with fallback
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "model:\n  provider: openai-codex\n"
            "fallback_providers:\n  - provider: custom\n"
            "    model: local-backup\n"
            "    base_url: http://localhost:11434/v1\n"
        )

        monkeypatch.setattr("gateway.run._marlow_home", tmp_path)

        call_count = {"n": 0}

        def _mock_resolve(**kwargs):
            call_count["n"] += 1
            # First call = primary path (gateway reads model.provider from
            # config.yaml internally; we simulate the auth failure here).
            # Second call = fallback path with explicit_api_key + explicit_base_url
            # supplied by gateway from fallback_providers config.
            if call_count["n"] == 1:
                raise AuthError("Codex token refresh failed with status 401")
            return {
                "api_key": "fallback-key",
                "base_url": "http://localhost:11434/v1",
                "provider": "custom",
                "api_mode": "chat_completions",
                "command": None,
                "args": None,
            }

        with patch(
            "marlow_cli.runtime_provider.resolve_runtime_provider",
            side_effect=_mock_resolve,
        ):
            from gateway.run import _resolve_runtime_agent_kwargs
            result = _resolve_runtime_agent_kwargs()

        assert result["provider"] == "custom"
        assert result["api_key"] == "fallback-key"
        # Should have been called at least twice (primary + fallback)
        assert call_count["n"] >= 2

    def test_auth_error_no_fallback_raises(self, tmp_path, monkeypatch):
        """When primary fails and no fallback configured, RuntimeError is raised."""
        from marlow_cli.auth import AuthError

        config_path = tmp_path / "config.yaml"
        config_path.write_text("model:\n  provider: openai-codex\n")

        monkeypatch.setattr("gateway.run._marlow_home", tmp_path)

        with patch(
            "marlow_cli.runtime_provider.resolve_runtime_provider",
            side_effect=AuthError("token expired"),
        ):
            from gateway.run import _resolve_runtime_agent_kwargs
            with pytest.raises(RuntimeError):
                _resolve_runtime_agent_kwargs()

    def test_fallback_providers_are_tried_in_order(self, tmp_path, monkeypatch):
        """Configured fallback entries participate in resolution in order."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "fallback_providers:\n"
            "  - provider: custom\n"
            "    model: local-a\n"
            "    base_url: http://localhost:11434/v1\n"
            "  - provider: openai-codex\n"
            "    model: gpt-5.3-codex\n"
        )

        monkeypatch.setattr("gateway.run._marlow_home", tmp_path)

        calls = []

        def _mock_resolve(**kwargs):
            requested = kwargs.get("requested")
            calls.append(requested)
            if requested == "custom":
                raise RuntimeError("custom endpoint unavailable")
            return {
                "api_key": "codex-key",
                "base_url": "https://chatgpt.com/backend-api/codex",
                "provider": "openai-codex",
                "api_mode": "codex_responses",
                "command": None,
                "args": None,
            }

        with patch(
            "marlow_cli.runtime_provider.resolve_runtime_provider",
            side_effect=_mock_resolve,
        ):
            from gateway.run import _try_resolve_fallback_provider

            result = _try_resolve_fallback_provider()

        assert calls == ["custom", "openai-codex"]
        assert result["provider"] == "openai-codex"
        assert result["model"] == "gpt-5.3-codex"
