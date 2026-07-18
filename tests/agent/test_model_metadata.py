"""Tests for agent/model_metadata.py — token estimation, context lengths,
probing, caching, and error parsing.

Coverage levels:
  Token estimation       — concrete value assertions, edge cases
  Context length lookup  — resolution order, fuzzy match, cache priority
  Endpoint metadata      — local/custom model discovery and caching
  Probe tiers            — descending, boundaries, extreme inputs
  Error parsing          — compatible endpoints, Ollama, edge cases
  Persistent cache       — save/load, corruption, update, provider isolation
"""

import time
import yaml
from unittest.mock import patch, MagicMock
from agent.model_metadata import (
    CONTEXT_PROBE_TIERS,
    DEFAULT_CONTEXT_LENGTHS,
    _strip_provider_prefix,
    estimate_tokens_rough,
    estimate_messages_tokens_rough,
    get_model_context_length,
    get_next_probe_tier,
    get_cached_context_length,
    parse_context_limit_from_error,
    save_context_length,
)


class TestEstimateTokensRough:
    def test_empty_string(self):
        assert estimate_tokens_rough("") == 0

    def test_none_returns_zero(self):
        assert estimate_tokens_rough(None) == 0

    def test_known_length(self):
        assert estimate_tokens_rough("a" * 400) == 100

    def test_short_text(self):
        assert estimate_tokens_rough("hello") == 2

    def test_proportional(self):
        short = estimate_tokens_rough("hello world")
        long = estimate_tokens_rough("hello world " * 100)
        assert long > short

    def test_unicode_multibyte(self):
        """Unicode chars are still 1 Python char each — 4 chars/token holds."""
        text = "你好世界"
        assert estimate_tokens_rough(text) == 1


class TestEstimateMessagesTokensRough:
    def test_empty_list(self):
        assert estimate_messages_tokens_rough([]) == 0

    def test_single_message_concrete_value(self):
        """Verify against known str(msg) length (ceiling division)."""
        msg = {"role": "user", "content": "a" * 400}
        result = estimate_messages_tokens_rough([msg])
        n = len(str(msg))
        expected = (n + 3) // 4
        assert result == expected

    def test_multiple_messages_additive(self):
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there, how can I help?"},
        ]
        result = estimate_messages_tokens_rough(msgs)
        n = sum((len(str(m)) for m in msgs))
        expected = (n + 3) // 4
        assert result == expected

    def test_tool_call_message(self):
        """Tool call messages with no 'content' key still contribute tokens."""
        msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "1", "function": {"name": "terminal", "arguments": "{}"}}
            ],
        }
        result = estimate_messages_tokens_rough([msg])
        assert result > 0
        assert result == (len(str(msg)) + 3) // 4

    def test_message_with_list_content(self):
        """Vision messages with multimodal content arrays.

        Image parts are counted at a flat ~1500-token rate per image
        rather than counting the base64 char length, so a tiny stub
        payload still registers as full image cost.
        """
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,AAAA"},
                },
            ],
        }
        result = estimate_messages_tokens_rough([msg])
        assert 1500 <= result < 2000

    def test_message_with_huge_base64_image_stays_bounded(self):
        """A 1MB base64 PNG must not explode to ~250K tokens."""
        huge = "A" * (1024 * 1024)
        msg = {
            "role": "tool",
            "tool_call_id": "c1",
            "content": [
                {"type": "text", "text": "x"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{huge}"},
                },
            ],
        }
        result = estimate_messages_tokens_rough([msg])
        assert result < 5000


class TestCodexOAuthContextLength:
    """ChatGPT Codex OAuth imposes lower context limits than the direct
    OpenAI API for the same slugs. Verified Apr 2026 via live probe of
    chatgpt.com/backend-api/codex/models: most models return 272k, while
    models.dev reports 1.05M for gpt-5.5/gpt-5.4 and 400k for the rest.
    (Known exception: gpt-5.3-codex-spark is 128k.)
    """

    def setup_method(self):
        import agent.model_metadata as mm

        mm._codex_oauth_context_cache = {}
        mm._codex_oauth_context_cache_time = 0.0

    def test_fallback_table_used_without_token(self):
        """With no access token, the hardcoded Codex fallback table wins
        over models.dev (which reports 1.05M for gpt-5.5 but Codex is 272k).
        """
        from agent.model_metadata import get_model_context_length

        expected = {
            "gpt-5.5": 272000,
            "gpt-5.4": 272000,
            "gpt-5.4-mini": 272000,
            "gpt-5.3-codex": 272000,
            "gpt-5.3-codex-spark": 128000,
            "gpt-5.2-codex": 272000,
            "gpt-5.1-codex-max": 272000,
            "gpt-5.1-codex-mini": 272000,
        }
        with (
            patch("agent.model_metadata.get_cached_context_length", return_value=None),
            patch("agent.model_metadata.save_context_length"),
        ):
            for model, expected_ctx in expected.items():
                ctx = get_model_context_length(
                    model=model,
                    base_url="https://chatgpt.com/backend-api/codex",
                    api_key="",
                    provider="openai-codex",
                )
                assert ctx == expected_ctx, (
                    f"Codex {model}: expected {expected_ctx} fallback, got {ctx} (models.dev leakage?)"
                )

    def test_live_probe_overrides_fallback(self):
        """When a token is provided, the live /models probe is preferred
        and its context_window drives the result."""
        from agent.model_metadata import get_model_context_length

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "models": [
                {"slug": "gpt-5.5", "context_window": 300000},
                {"slug": "gpt-5.4", "context_window": 400000},
            ]
        }
        with (
            patch("agent.model_metadata.requests.get", return_value=fake_response),
            patch("agent.model_metadata.get_cached_context_length", return_value=None),
            patch("agent.model_metadata.save_context_length"),
        ):
            ctx_55 = get_model_context_length(
                model="gpt-5.5",
                base_url="https://chatgpt.com/backend-api/codex",
                api_key="fake-token",
                provider="openai-codex",
            )
            ctx_54 = get_model_context_length(
                model="gpt-5.4",
                base_url="https://chatgpt.com/backend-api/codex",
                api_key="fake-token",
                provider="openai-codex",
            )
        assert ctx_55 == 300000
        assert ctx_54 == 400000

    def test_probe_failure_falls_back_to_hardcoded(self):
        """If the probe fails (non-200 / network error), we still return
        the hardcoded 272k rather than leaking through to models.dev 1.05M."""
        from agent.model_metadata import get_model_context_length

        fake_response = MagicMock()
        fake_response.status_code = 401
        fake_response.json.return_value = {}
        with (
            patch("agent.model_metadata.requests.get", return_value=fake_response),
            patch("agent.model_metadata.get_cached_context_length", return_value=None),
            patch("agent.model_metadata.save_context_length"),
        ):
            ctx = get_model_context_length(
                model="gpt-5.5",
                base_url="https://chatgpt.com/backend-api/codex",
                api_key="expired-token",
                provider="openai-codex",
            )
        assert ctx == 272000

    def test_stale_codex_cache_over_400k_is_invalidated(self, tmp_path, monkeypatch):
        """Pre-PR #14935 builds cached gpt-5.5 at 1.05M (from models.dev)
        before the Codex-aware branch existed. Upgrading users keep that
        stale entry on disk and the cache-first lookup returns it forever.
        Codex OAuth caps at 272k for every slug, so any cached Codex
        entry >= 400k must be dropped and re-resolved via the live probe.
        """
        from agent import model_metadata as mm

        cache_file = tmp_path / "context_length_cache.yaml"
        monkeypatch.setattr(mm, "_get_context_cache_path", lambda: cache_file)
        base_url = "https://chatgpt.com/backend-api/codex/"
        stale_key = f"gpt-5.5@{base_url}"
        other_key = "other-model@https://api.openai.com/v1/"
        import yaml as _yaml

        cache_file.write_text(
            _yaml.dump({"context_lengths": {stale_key: 1050000, other_key: 128000}})
        )
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "models": [{"slug": "gpt-5.5", "context_window": 272000}]
        }
        with (
            patch("agent.model_metadata.requests.get", return_value=fake_response),
            patch("agent.model_metadata.save_context_length") as mock_save,
        ):
            ctx = mm.get_model_context_length(
                model="gpt-5.5",
                base_url=base_url,
                api_key="fake-token",
                provider="openai-codex",
            )
        assert ctx == 272000, (
            f"Stale entry should have been re-resolved to 272k, got {ctx}"
        )
        mock_save.assert_called_with("gpt-5.5", base_url, 272000)
        remaining = _yaml.safe_load(cache_file.read_text()).get("context_lengths", {})
        assert stale_key not in remaining, (
            "Stale entry was not invalidated from the cache file"
        )
        assert remaining.get(other_key) == 128000, (
            "Unrelated cache entries must not be touched"
        )

    def test_fresh_codex_cache_under_400k_is_respected(self, tmp_path, monkeypatch):
        """Codex entries at the correct 272k must NOT be invalidated —
        only stale pre-fix values (>= 400k) get dropped."""
        from agent import model_metadata as mm

        cache_file = tmp_path / "context_length_cache.yaml"
        monkeypatch.setattr(mm, "_get_context_cache_path", lambda: cache_file)
        base_url = "https://chatgpt.com/backend-api/codex/"
        import yaml as _yaml

        cache_file.write_text(
            _yaml.dump({"context_lengths": {f"gpt-5.5@{base_url}": 272000}})
        )
        with patch("agent.model_metadata.requests.get") as mock_get:
            ctx = mm.get_model_context_length(
                model="gpt-5.5",
                base_url=base_url,
                api_key="fake-token",
                provider="openai-codex",
            )
        assert ctx == 272000
        mock_get.assert_not_called()


class TestGetModelContextLength:
    def test_fallback_to_defaults(self):
        assert get_model_context_length("local/llama-3.3-70b") == 131072

    def test_unknown_model_returns_first_probe_tier(self):
        assert (
            get_model_context_length("unknown/never-heard-of-this")
            == CONTEXT_PROBE_TIERS[0]
        )

    def test_partial_match_in_defaults(self):
        assert get_model_context_length("local/gpt-4o-compatible") == 128000

    def test_cache_takes_priority_over_endpoint_metadata(self, tmp_path):
        """Persistent cache should be checked before endpoint metadata."""
        cache_file = tmp_path / "cache.yaml"
        with patch(
            "agent.model_metadata._get_context_cache_path", return_value=cache_file
        ):
            save_context_length("my/model", "http://local", 32768)
            result = get_model_context_length("my/model", base_url="http://local")
            assert result == 32768

    def test_no_base_url_skips_cache(self, tmp_path):
        """Without base_url, cache lookup is skipped."""
        cache_file = tmp_path / "cache.yaml"
        with patch(
            "agent.model_metadata._get_context_cache_path", return_value=cache_file
        ):
            save_context_length("custom/model", "http://local", 32768)
            result = get_model_context_length("custom/model")
            assert result == CONTEXT_PROBE_TIERS[0]

    @patch("agent.model_metadata.fetch_endpoint_model_metadata")
    def test_custom_endpoint_metadata_beats_fuzzy_default(self, mock_endpoint_fetch):
        mock_endpoint_fetch.return_value = {
            "zai-org/GLM-5-TEE": {"context_length": 65536}
        }
        result = get_model_context_length(
            "zai-org/GLM-5-TEE", base_url="https://llm.chutes.ai/v1", api_key="test-key"
        )
        assert result == 65536

    @patch("agent.model_metadata.fetch_endpoint_model_metadata")
    def test_custom_endpoint_without_metadata_uses_local_model_default(
        self, mock_endpoint_fetch
    ):
        mock_endpoint_fetch.return_value = {}
        result = get_model_context_length(
            "zai-org/GLM-5-TEE", base_url="https://llm.chutes.ai/v1", api_key="test-key"
        )
        assert result == 202752

    @patch("agent.model_metadata.fetch_endpoint_model_metadata")
    def test_custom_endpoint_single_model_fallback(self, mock_endpoint_fetch):
        """Single-model servers: use the only model even if name doesn't match."""
        mock_endpoint_fetch.return_value = {
            "Qwen3.5-9B-Q4_K_M.gguf": {"context_length": 131072}
        }
        result = get_model_context_length(
            "qwen3.5:9b",
            base_url="http://myserver.example.com:8080/v1",
            api_key="test-key",
        )
        assert result == 131072

    @patch("agent.model_metadata.fetch_endpoint_model_metadata")
    def test_custom_endpoint_fuzzy_substring_match(self, mock_endpoint_fetch):
        """Fuzzy match: configured model name is substring of endpoint model."""
        mock_endpoint_fetch.return_value = {
            "org/llama-3.3-70b-instruct-fp8": {"context_length": 131072},
            "org/qwen-2.5-72b": {"context_length": 32768},
        }
        result = get_model_context_length(
            "llama-3.3-70b-instruct",
            base_url="http://myserver.example.com:8080/v1",
            api_key="test-key",
        )
        assert result == 131072

    def test_config_context_length_overrides_all(self):
        """Explicit config_context_length takes priority over everything."""
        result = get_model_context_length("test/model", config_context_length=65536)
        assert result == 65536

    def test_config_context_length_zero_is_ignored(self):
        """config_context_length=0 should be treated as unset."""
        result = get_model_context_length(
            "anthropic/claude-sonnet-4", config_context_length=0
        )
        assert result == 200000

    def test_config_context_length_none_is_ignored(self):
        """config_context_length=None should be treated as unset."""
        result = get_model_context_length(
            "anthropic/claude-sonnet-4", config_context_length=None
        )
        assert result == 200000


class TestStripProviderPrefix:
    def test_ollama_model_tag_preserved(self):
        """Ollama model:tag format must NOT be stripped."""
        assert _strip_provider_prefix("qwen3.5:27b") == "qwen3.5:27b"
        assert _strip_provider_prefix("llama3.3:70b") == "llama3.3:70b"
        assert _strip_provider_prefix("gemma2:9b") == "gemma2:9b"
        assert (
            _strip_provider_prefix("codellama:13b-instruct-q4_0")
            == "codellama:13b-instruct-q4_0"
        )

    def test_http_urls_preserved(self):
        assert _strip_provider_prefix("http://example.com") == "http://example.com"
        assert _strip_provider_prefix("https://example.com") == "https://example.com"

    def test_no_colon_returns_unchanged(self):
        assert _strip_provider_prefix("gpt-4o") == "gpt-4o"
        assert (
            _strip_provider_prefix("anthropic/claude-sonnet-4")
            == "anthropic/claude-sonnet-4"
        )

    def test_ollama_model_tag_not_mangled_in_context_lookup(self):
        """Ensure 'qwen3.5:27b' is NOT reduced to '27b' during context length lookup.

        We mock a custom endpoint that knows 'qwen3.5:27b' — the full name
        must reach the endpoint metadata lookup intact.
        """
        with patch("agent.model_metadata.fetch_endpoint_model_metadata") as mock_ep:
            mock_ep.return_value = {"qwen3.5:27b": {"context_length": 32768}}
            result = get_model_context_length(
                "qwen3.5:27b", base_url="http://localhost:11434/v1"
            )
        assert result == 32768


class TestContextProbeTiers:
    def test_tiers_descending(self):
        for i in range(len(CONTEXT_PROBE_TIERS) - 1):
            assert CONTEXT_PROBE_TIERS[i] > CONTEXT_PROBE_TIERS[i + 1]


class TestGetNextProbeTier:
    def test_from_256k(self):
        assert get_next_probe_tier(256000) == 128000

    def test_from_128k(self):
        assert get_next_probe_tier(128000) == 64000

    def test_from_64k(self):
        assert get_next_probe_tier(64000) == 32000

    def test_from_32k(self):
        assert get_next_probe_tier(32000) == 16000

    def test_from_8k_returns_none(self):
        assert get_next_probe_tier(8000) is None

    def test_from_below_min_returns_none(self):
        assert get_next_probe_tier(4000) is None

    def test_from_arbitrary_value(self):
        assert get_next_probe_tier(100000) == 64000

    def test_above_max_tier(self):
        """Value above 256K should return 256K."""
        assert get_next_probe_tier(500000) == 256000

    def test_zero_returns_none(self):
        assert get_next_probe_tier(0) is None


class TestParseContextLimitFromError:
    def test_openai_format(self):
        msg = "This model's maximum context length is 32768 tokens. However, your messages resulted in 45000 tokens."
        assert parse_context_limit_from_error(msg) == 32768

    def test_context_length_exceeded(self):
        msg = "context_length_exceeded: maximum context length is 131072"
        assert parse_context_limit_from_error(msg) == 131072

    def test_context_size_exceeded(self):
        msg = "Maximum context size 65536 exceeded"
        assert parse_context_limit_from_error(msg) == 65536

    def test_no_limit_in_message(self):
        assert (
            parse_context_limit_from_error("Something went wrong with the API") is None
        )

    def test_unreasonable_small_number_rejected(self):
        assert parse_context_limit_from_error("context length is 42 tokens") is None

    def test_ollama_format(self):
        msg = "Context size has been exceeded. Maximum context size is 32768"
        assert parse_context_limit_from_error(msg) == 32768

    def test_lmstudio_format(self):
        msg = "Error: context window of 4096 tokens exceeded"
        assert parse_context_limit_from_error(msg) == 4096

    def test_completely_unrelated_error(self):
        assert parse_context_limit_from_error("Invalid API key") is None

    def test_empty_string(self):
        assert parse_context_limit_from_error("") is None

    def test_number_outside_reasonable_range(self):
        """Very large number (>10M) should be rejected."""
        msg = "maximum context length is 99999999999"
        assert parse_context_limit_from_error(msg) is None


class TestContextLengthCache:
    def test_save_and_load(self, tmp_path):
        cache_file = tmp_path / "cache.yaml"
        with patch(
            "agent.model_metadata._get_context_cache_path", return_value=cache_file
        ):
            save_context_length("test/model", "http://localhost:8080/v1", 32768)
            assert (
                get_cached_context_length("test/model", "http://localhost:8080/v1")
                == 32768
            )

    def test_missing_cache_returns_none(self, tmp_path):
        cache_file = tmp_path / "nonexistent.yaml"
        with patch(
            "agent.model_metadata._get_context_cache_path", return_value=cache_file
        ):
            assert get_cached_context_length("test/model", "http://x") is None

    def test_multiple_models_cached(self, tmp_path):
        cache_file = tmp_path / "cache.yaml"
        with patch(
            "agent.model_metadata._get_context_cache_path", return_value=cache_file
        ):
            save_context_length("model-a", "http://a", 64000)
            save_context_length("model-b", "http://b", 128000)
            assert get_cached_context_length("model-a", "http://a") == 64000
            assert get_cached_context_length("model-b", "http://b") == 128000

    def test_same_model_different_providers(self, tmp_path):
        cache_file = tmp_path / "cache.yaml"
        with patch(
            "agent.model_metadata._get_context_cache_path", return_value=cache_file
        ):
            save_context_length("llama-3", "http://local:8080", 32768)
            save_context_length("llama-3", "https://openrouter.ai/api/v1", 131072)
            assert get_cached_context_length("llama-3", "http://local:8080") == 32768
            assert (
                get_cached_context_length("llama-3", "https://openrouter.ai/api/v1")
                == 131072
            )

    def test_idempotent_save(self, tmp_path):
        cache_file = tmp_path / "cache.yaml"
        with patch(
            "agent.model_metadata._get_context_cache_path", return_value=cache_file
        ):
            save_context_length("model", "http://x", 32768)
            save_context_length("model", "http://x", 32768)
            with open(cache_file) as f:
                data = yaml.safe_load(f)
            assert len(data["context_lengths"]) == 1

    def test_update_existing_value(self, tmp_path):
        """Saving a different value for the same key overwrites it."""
        cache_file = tmp_path / "cache.yaml"
        with patch(
            "agent.model_metadata._get_context_cache_path", return_value=cache_file
        ):
            save_context_length("model", "http://x", 128000)
            save_context_length("model", "http://x", 64000)
            assert get_cached_context_length("model", "http://x") == 64000

    def test_corrupted_yaml_returns_empty(self, tmp_path):
        """Corrupted cache file is handled gracefully."""
        cache_file = tmp_path / "cache.yaml"
        cache_file.write_text("{{{{not valid yaml: [[[")
        with patch(
            "agent.model_metadata._get_context_cache_path", return_value=cache_file
        ):
            assert get_cached_context_length("model", "http://x") is None

    def test_wrong_structure_returns_none(self, tmp_path):
        """YAML that loads but has wrong structure."""
        cache_file = tmp_path / "cache.yaml"
        cache_file.write_text("just_a_string\n")
        with patch(
            "agent.model_metadata._get_context_cache_path", return_value=cache_file
        ):
            assert get_cached_context_length("model", "http://x") is None

    def test_cached_value_takes_priority(self, tmp_path):
        cache_file = tmp_path / "cache.yaml"
        with patch(
            "agent.model_metadata._get_context_cache_path", return_value=cache_file
        ):
            save_context_length("unknown/model", "http://local", 65536)
            assert (
                get_model_context_length("unknown/model", base_url="http://local")
                == 65536
            )

    def test_special_chars_in_model_name(self, tmp_path):
        """Model names with colons, slashes, etc. don't break the cache."""
        cache_file = tmp_path / "cache.yaml"
        model = "anthropic/claude-3.5-sonnet:beta"
        url = "https://api.example.com/v1"
        with patch(
            "agent.model_metadata._get_context_cache_path", return_value=cache_file
        ):
            save_context_length(model, url, 200000)
            assert get_cached_context_length(model, url) == 200000
