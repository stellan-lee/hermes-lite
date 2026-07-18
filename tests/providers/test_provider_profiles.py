"""Tests for the retained model-provider registry."""

from providers import _REGISTRY, get_provider_profile, list_providers


def test_retained_profiles_are_exactly_codex_and_custom():
    assert {profile.name for profile in list_providers()} == {"custom", "openai-codex"}


def test_custom_profile_supports_openai_compatible_endpoints():
    profile = get_provider_profile("custom")
    assert profile is not None
    assert profile.name == "custom"
    assert profile.api_mode == "chat_completions"
    assert profile.env_vars == ()
    assert "ollama" in profile.aliases


def test_codex_profile_uses_codex_runtime():
    profile = get_provider_profile("openai-codex")
    assert profile is not None
    assert profile.name == "openai-codex"


def test_unknown_provider_returns_none():
    assert get_provider_profile("nonexistent-provider") is None


def test_registry_keys_match_profile_names():
    list_providers()
    assert all(profile.name == name for name, profile in _REGISTRY.items())
