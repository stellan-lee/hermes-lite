"""Tests for user-defined providers (providers: dict) in /model.

These tests ensure that providers defined in the config.yaml ``providers:`` section
are properly resolved for model switching and that their full ``models:`` lists
are exposed in the model picker.
"""

import pytest
from hermes_cli.model_switch import list_authenticated_providers, switch_model
from hermes_cli import runtime_provider as rp


# =============================================================================
# Tests for list_authenticated_providers including full models list
# =============================================================================

def test_list_authenticated_providers_includes_full_models_list_from_user_providers(monkeypatch):
    """User-defined providers expose the selected model and model map."""
    monkeypatch.setattr("hermes_cli.providers.HERMES_OVERLAYS", {})
    
    user_providers = {
        "local-ollama": {
            "name": "Local Ollama",
            "base_url": "http://localhost:11434/v1",
            "model": "minimax-m2.7:cloud",
            "models": {
                "minimax-m2.7:cloud": {},
                "kimi-k2.5:cloud": {},
                "glm-5.1:cloud": {},
                "qwen3.5:cloud": {},
            },
        }
    }
    
    providers = list_authenticated_providers(
        current_provider="local-ollama",
        user_providers=user_providers,
        custom_providers=[],
        max_models=50,
    )
    
    # Find our user provider
    user_prov = next(
        (p for p in providers if p.get("is_user_defined") and p["slug"] == "local-ollama"),
        None
    )
    
    assert user_prov is not None, "User provider 'local-ollama' should be in results"
    assert user_prov["total_models"] == 4, f"Expected 4 models, got {user_prov['total_models']}"
    assert "minimax-m2.7:cloud" in user_prov["models"]
    assert "kimi-k2.5:cloud" in user_prov["models"]
    assert "glm-5.1:cloud" in user_prov["models"]
    assert "qwen3.5:cloud" in user_prov["models"]


def test_list_authenticated_providers_dedupes_models_when_default_in_list(monkeypatch):
    """When model is also in the models map, don't duplicate it."""
    monkeypatch.setattr("hermes_cli.providers.HERMES_OVERLAYS", {})
    
    user_providers = {
        "my-provider": {
            "base_url": "http://example.com/v1",
            "model": "model-a",
            "models": {"model-a": {}, "model-b": {}, "model-c": {}},
        }
    }
    
    providers = list_authenticated_providers(
        current_provider="my-provider",
        user_providers=user_providers,
        custom_providers=[],
    )
    
    user_prov = next(
        (p for p in providers if p.get("is_user_defined")),
        None
    )
    
    assert user_prov is not None
    assert user_prov["total_models"] == 3, "Should have 3 unique models, not 4"
    assert user_prov["models"].count("model-a") == 1, "model-a should not be duplicated"


def test_list_authenticated_providers_enumerates_dict_format_models(monkeypatch):
    """providers: dict entries with ``models:`` as a dict keyed by model id
    (canonical Hermes write format) should surface every key in the picker.

    Regression: the ``providers:`` dict path previously only accepted
    list-format ``models:`` and silently dropped dict-format entries,
    even though Hermes's own writer and downstream readers use dict format.
    """
    monkeypatch.setattr("hermes_cli.providers.HERMES_OVERLAYS", {})

    user_providers = {
        "local-ollama": {
            "name": "Local Ollama",
            "base_url": "http://localhost:11434/v1",
            "model": "minimax-m2.7:cloud",
            "models": {
                "minimax-m2.7:cloud": {"context_length": 196608},
                "kimi-k2.5:cloud": {"context_length": 200000},
                "glm-5.1:cloud": {"context_length": 202752},
            },
        }
    }

    providers = list_authenticated_providers(
        current_provider="local-ollama",
        user_providers=user_providers,
        custom_providers=[],
        max_models=50,
    )

    user_prov = next(
        (p for p in providers if p.get("is_user_defined") and p["slug"] == "local-ollama"),
        None,
    )

    assert user_prov is not None
    assert user_prov["total_models"] == 3
    assert user_prov["models"] == [
        "minimax-m2.7:cloud",
        "kimi-k2.5:cloud",
        "glm-5.1:cloud",
    ]


def test_list_authenticated_providers_uses_live_models_for_user_provider(monkeypatch):
    """User-defined OpenAI-compatible providers should prefer live /models.

    Regression: CRS-style providers with a stale config ``models:`` dict kept
    showing only the configured subset in the /model picker, even though their
    /v1/models endpoint exposed newly added models.
    """
    monkeypatch.setattr("hermes_cli.providers.HERMES_OVERLAYS", {})
    monkeypatch.setenv("CRS_TEST_KEY", "sk-test")

    calls = []

    def fake_fetch_api_models(api_key, base_url):
        calls.append((api_key, base_url))
        return ["old-configured-model", "new-live-model"]

    monkeypatch.setattr("hermes_cli.models.fetch_api_models", fake_fetch_api_models)

    user_providers = {
        "crs-henkee": {
            "name": "CRS Henkee",
            "base_url": "http://127.0.0.1:3000/api/v1",
            "key_env": "CRS_TEST_KEY",
            "model": "old-configured-model",
            "models": {
                "old-configured-model": {"context_length": 200000},
            },
        }
    }

    providers = list_authenticated_providers(
        current_provider="crs-henkee",
        user_providers=user_providers,
        custom_providers=[],
        max_models=50,
    )

    user_prov = next(
        (p for p in providers if p.get("is_user_defined") and p["slug"] == "crs-henkee"),
        None,
    )

    assert user_prov is not None
    assert calls == [("sk-test", "http://127.0.0.1:3000/api/v1")]
    assert user_prov["models"] == ["old-configured-model", "new-live-model"]
    assert user_prov["total_models"] == 2


def test_list_authenticated_providers_dict_models_without_selected_model(monkeypatch):
    """Dict-format ``models:`` without a selected model must still expose
    every dict key, not collapse to an empty list."""
    monkeypatch.setattr("hermes_cli.providers.HERMES_OVERLAYS", {})

    user_providers = {
        "multimodel": {
            "base_url": "http://example.com/v1",
            "models": {
                "alpha": {"context_length": 8192},
                "beta": {"context_length": 16384},
            },
        }
    }

    providers = list_authenticated_providers(
        current_provider="",
        user_providers=user_providers,
        custom_providers=[],
    )

    user_prov = next(
        (p for p in providers if p.get("is_user_defined") and p["slug"] == "multimodel"),
        None,
    )

    assert user_prov is not None
    assert user_prov["total_models"] == 2
    assert set(user_prov["models"]) == {"alpha", "beta"}


def test_list_authenticated_providers_dict_models_dedupe_with_default(monkeypatch):
    """When ``model`` is also a key in ``models:``, it appears once."""
    monkeypatch.setattr("hermes_cli.providers.HERMES_OVERLAYS", {})

    user_providers = {
        "my-provider": {
            "base_url": "http://example.com/v1",
            "model": "model-a",
            "models": {
                "model-a": {"context_length": 8192},
                "model-b": {"context_length": 16384},
                "model-c": {"context_length": 32768},
            },
        }
    }

    providers = list_authenticated_providers(
        current_provider="my-provider",
        user_providers=user_providers,
        custom_providers=[],
    )

    user_prov = next(
        (p for p in providers if p.get("is_user_defined")),
        None,
    )

    assert user_prov is not None
    assert user_prov["total_models"] == 3
    assert user_prov["models"].count("model-a") == 1



def test_list_authenticated_providers_fallback_to_default_only(monkeypatch):
    """When no models map is provided, fall back to the selected model."""
    monkeypatch.setattr("hermes_cli.providers.HERMES_OVERLAYS", {})
    
    user_providers = {
        "simple-provider": {
            "name": "Simple Provider",
            "base_url": "http://example.com/v1",
            "model": "single-model",
            # No 'models' key
        }
    }
    
    providers = list_authenticated_providers(
        current_provider="",
        user_providers=user_providers,
        custom_providers=[],
    )
    
    user_prov = next(
        (p for p in providers if p.get("is_user_defined")),
        None
    )
    
    assert user_prov is not None
    assert user_prov["total_models"] == 1
    assert user_prov["models"] == ["single-model"]


def test_list_authenticated_providers_accepts_base_url_and_singular_model(monkeypatch):
    """providers: dict entries written in canonical Hermes shape
    (``base_url`` + singular ``model``) should resolve directly.
    """
    monkeypatch.setattr("hermes_cli.providers.HERMES_OVERLAYS", {})

    user_providers = {
        "custom": {
            "base_url": "http://example.com/v1",
            "model": "gpt-5.4",
            "models": {
                "gpt-5.4": {},
                "grok-4.20-beta": {},
                "minimax-m2.7": {},
            },
        }
    }

    providers = list_authenticated_providers(
        current_provider="custom",
        user_providers=user_providers,
        custom_providers=[],
        max_models=50,
    )

    custom = next((p for p in providers if p["slug"] == "custom"), None)
    assert custom is not None
    assert custom["api_url"] == "http://example.com/v1"
    assert custom["models"] == ["gpt-5.4", "grok-4.20-beta", "minimax-m2.7"]
    assert custom["total_models"] == 3


def test_get_named_custom_provider_finds_user_providers_by_key(monkeypatch, tmp_path):
    """Should resolve a canonical provider by its dictionary key."""
    config = {
        "providers": {
            "local-localhost:11434": {
                "base_url": "http://localhost:11434/v1",
                "name": "Local (localhost:11434)",
                "model": "minimax-m2.7:cloud",
            }
        }
    }
    
    import yaml
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config))
    
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    
    result = rp._get_named_custom_provider("local-localhost:11434")
    
    assert result is not None
    assert result["base_url"] == "http://localhost:11434/v1"
    assert result["name"] == "Local (localhost:11434)"


def test_get_named_custom_provider_finds_by_display_name(monkeypatch, tmp_path):
    """Should match providers by their 'name' field as well as key."""
    config = {
        "providers": {
            "my-ollama-xyz": {
                "base_url": "http://ollama.example.com/v1",
                "name": "My Production Ollama",
                "model": "llama3",
            }
        }
    }
    
    import yaml
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config))
    
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    
    # Should find by display name (normalized)
    result = rp._get_named_custom_provider("my-production-ollama")
    
    assert result is not None
    assert result["base_url"] == "http://ollama.example.com/v1"


def test_get_named_custom_provider_returns_none_for_unknown(monkeypatch, tmp_path):
    """Should return None for providers that don't exist."""
    config = {
        "providers": {
            "known-provider": {
                "base_url": "http://known.example.com/v1",
            }
        }
    }
    
    import yaml
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config))
    
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    
    result = rp._get_named_custom_provider("other-provider")
    
    # "unknown-provider" partial-matches "known-provider" because "unknown" doesn't match
    # but our matching is loose (substring). Let's verify a truly non-matching provider
    result = rp._get_named_custom_provider("completely-different-name")
    assert result is None


def test_get_named_custom_provider_skips_empty_base_url(monkeypatch, tmp_path):
    """Should skip providers without a base_url."""
    config = {
        "providers": {
            "incomplete-provider": {
                "name": "Incomplete",
                # No api/base_url field
            }
        }
    }
    
    import yaml
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config))
    
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    
    result = rp._get_named_custom_provider("incomplete-provider")
    
    assert result is None


# =============================================================================
# Integration test for switch_model with user providers
# =============================================================================

def test_switch_model_resolves_user_provider_credentials(monkeypatch, tmp_path):
    """/model switch should resolve credentials for providers: dict providers."""
    import yaml
    
    config = {
        "providers": {
            "local-ollama": {
                "base_url": "http://localhost:11434/v1",
                "name": "Local Ollama",
                "model": "minimax-m2.7:cloud",
            }
        }
    }
    
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    
    # Mock validation to pass
    monkeypatch.setattr(
        "hermes_cli.models.validate_requested_model",
        lambda *a, **k: {"accepted": True, "persist": True, "recognized": True, "message": None}
    )
    
    result = switch_model(
        raw_input="kimi-k2.5:cloud",
        current_provider="local-ollama",
        current_model="minimax-m2.7:cloud",
        current_base_url="http://localhost:11434/v1",
        is_global=False,
        user_providers=config["providers"],
    )

    assert result.success is True
    assert result.error_message == ""


# =============================================================================
# Canonical provider ``api_mode`` must be honored
# =============================================================================


def test_get_named_custom_provider_reads_api_mode(monkeypatch):
    config = {
        "_config_version": 12,
        "providers": {
            "my-codex-provider": {
                "name": "my-codex-provider",
                "base_url": "http://127.0.0.1:4000/v1",
                "api_key": "test-key",
                "model": "gpt-5",
                "api_mode": "codex_responses",
            },
        },
    }

    monkeypatch.setattr(rp, "load_config", lambda: config)

    result = rp._get_named_custom_provider("my-codex-provider")
    assert result is not None
    assert result["api_mode"] == "codex_responses"
    assert result["base_url"] == "http://127.0.0.1:4000/v1"
    assert result["model"] == "gpt-5"



def test_get_named_custom_provider_api_mode_resolves_via_display_name(monkeypatch):
    """When the requested name matches the entry's ``name:`` field rather
    than its dict key, the same transport-vs-api_mode logic must apply
    (second branch in ``_get_named_custom_provider``)."""
    config = {
        "_config_version": 12,
        "providers": {
            "slug-different-from-name": {
                "name": "Codex Provider",  # display name
                "base_url": "http://127.0.0.1:4000/v1",
                "api_key": "test-key",
                "model": "gpt-5",
                "api_mode": "codex_responses",
            },
        },
    }

    monkeypatch.setattr(rp, "load_config", lambda: config)

    result = rp._get_named_custom_provider("Codex Provider")
    assert result is not None
    assert result["api_mode"] == "codex_responses"


# =============================================================================
# Regression: user_providers override for private models not listed by /v1/models
# =============================================================================

_REJECTED_VALIDATION = {
    "accepted": False,
    "persist": False,
    "recognized": False,
    "message": "not found",
}


def _run_user_provider_override_case(
    *,
    slug,
    name,
    base_url,
    models,
    raw_input,
):
    """Run ``switch_model`` with a private user provider and a rejected API check.

    The bug in PR #17964 was that ``user_providers`` was treated like a list,
    so private models listed in ``models:`` never triggered the override path.
    These tests keep the validation failure in place and prove the config list
    still wins for both dict- and list-shaped ``models`` entries.
    """
    from unittest.mock import patch

    user_providers = {
        slug: {
            "name": name,
            "base_url": base_url,
            "discover_models": False,
            "models": models,
        }
    }

    with patch("hermes_cli.model_switch.resolve_alias", return_value=None), \
         patch("hermes_cli.model_switch.normalize_model_for_provider", side_effect=lambda model, provider: model), \
         patch("hermes_cli.models.validate_requested_model", return_value=_REJECTED_VALIDATION), \
         patch("hermes_cli.models.detect_provider_for_model", return_value=None), \
         patch("hermes_cli.runtime_provider.resolve_runtime_provider", return_value={"api_key": "***", "base_url": base_url, "api_mode": "chat_completions"}):
        return switch_model(
            raw_input=raw_input,
            current_provider=slug,
            current_model="old-model",
            current_base_url=base_url,
            user_providers=user_providers,
            custom_providers=[],
        )


@pytest.mark.parametrize(
    ("slug", "name", "base_url", "models", "raw_input", "expected_model"),
    [
        (
            "private-local",
            "Private Local",
            "http://127.0.0.1:4000/v1",
            {"private-model": {}},
            "private-model",
            "private-model",
        ),
    ],
    ids=["configured-private-model"],
)
def test_user_provider_override_accepts_listed_private_models(
    slug,
    name,
    base_url,
    models,
    raw_input,
    expected_model,
):
    """Private models listed in providers: config should override /v1/models misses.

    Covers the retained dict model schema for a configured endpoint.
    """
    result = _run_user_provider_override_case(
        slug=slug,
        name=name,
        base_url=base_url,
        models=models,
        raw_input=raw_input,
    )

    assert result.success is True
    assert result.new_model == expected_model
    assert result.error_message == ""


@pytest.mark.parametrize(
    ("slug", "name", "base_url", "models", "raw_input"),
    [
        (
            "private-local",
            "Private Local",
            "http://127.0.0.1:4000/v1",
            {"private-model": {}},
            "private-model-mangled",
        ),
    ],
    ids=["private-dict-mangled"],
)
def test_user_provider_override_rejects_mangled_private_models(
    slug,
    name,
    base_url,
    models,
    raw_input,
):
    """Malformed model names should fail cleanly, not crash or auto-accept."""
    result = _run_user_provider_override_case(
        slug=slug,
        name=name,
        base_url=base_url,
        models=models,
        raw_input=raw_input,
    )

    assert result.success is False
    assert result.error_message == "not found"
