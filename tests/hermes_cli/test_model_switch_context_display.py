"""Provider-aware context-length display for retained runtimes."""
from __future__ import annotations

from unittest.mock import patch

from hermes_cli.model_switch import resolve_display_context_length


class TestResolveDisplayContextLength:
    def test_codex_oauth_context(self):
        with patch(
            "agent.model_metadata.get_model_context_length",
            return_value=272_000,  # what Codex OAuth actually enforces
        ):
            ctx = resolve_display_context_length(
                "gpt-5.5",
                "openai-codex",
                base_url="https://chatgpt.com/backend-api/codex",
                api_key="",
            )
        assert ctx == 272_000

    def test_returns_none_when_resolver_empty(self):
        with patch(
            "agent.model_metadata.get_model_context_length", return_value=None
        ):
            ctx = resolve_display_context_length(
                "unknown-model",
                "unknown-provider",
            )
        assert ctx is None

    def test_resolver_exception_returns_none(self):
        with patch(
            "agent.model_metadata.get_model_context_length",
            side_effect=RuntimeError("network down"),
        ):
            ctx = resolve_display_context_length("x", "y")
        assert ctx is None

    def test_returns_resolver_value(self):
        with patch(
            "agent.model_metadata.get_model_context_length", return_value=128_000
        ):
            ctx = resolve_display_context_length(
                "capped-model",
                "capped-provider",
            )
        assert ctx == 128_000

    def test_custom_providers_override_honored(self):
        """Regression for #15779: /model switch onto a custom provider must
        surface the configured per-model context_length, not the 128K/256K
        fallback.
        """
        custom_provs = [
            {
                "name": "my-custom-endpoint",
                "base_url": "https://example.invalid/v1",
                "models": {"gpt-5.5": {"context_length": 1_050_000}},
            }
        ]
        # Real resolver call — no mock — so the override path is exercised
        # through agent.model_metadata.get_model_context_length.
        from unittest.mock import patch as _p
        from agent import model_metadata as _mm
        with _p.object(_mm, "get_cached_context_length", return_value=None), \
             _p.object(_mm, "fetch_endpoint_model_metadata", return_value={}), \
             _p.object(_mm, "is_local_endpoint", return_value=False):
            ctx = resolve_display_context_length(
                "gpt-5.5",
                "custom",
                base_url="https://example.invalid/v1",
                api_key="k",
                custom_providers=custom_provs,
            )
        assert ctx == 1_050_000, (
            "custom_providers[].models.gpt-5.5.context_length=1.05M must win "
            "over probe-down fallback"
        )

    def test_custom_providers_trailing_slash_insensitive(self):
        """Base URL comparison must tolerate trailing-slash differences
        between config.yaml and the runtime value.
        """
        custom_provs = [
            {
                "base_url": "https://example.invalid/v1/",
                "models": {"m": {"context_length": 400_000}},
            }
        ]
        from unittest.mock import patch as _p
        from agent import model_metadata as _mm
        with _p.object(_mm, "get_cached_context_length", return_value=None), \
             _p.object(_mm, "fetch_endpoint_model_metadata", return_value={}), \
             _p.object(_mm, "is_local_endpoint", return_value=False):
            ctx = resolve_display_context_length(
                "m",
                "custom",
                base_url="https://example.invalid/v1",  # no trailing slash
                custom_providers=custom_provs,
            )
        assert ctx == 400_000
