import json

from hermes_cli.codex_models import DEFAULT_CODEX_MODELS, get_codex_model_ids


def test_get_codex_model_ids_prioritizes_default_and_cache(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "config.toml").write_text('model = "gpt-5.2-codex"\n')
    (codex_home / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {"slug": "gpt-5.3-codex", "priority": 20, "supported_in_api": True},
                    {
                        "slug": "gpt-5.3-codex-spark",
                        "priority": 6,
                        "supported_in_api": False,
                    },
                    {"slug": "gpt-5.1-codex", "priority": 5, "supported_in_api": True},
                    {"slug": "gpt-5.4", "priority": 1, "supported_in_api": True},
                    {"slug": "gpt-5-hidden-codex", "priority": 2, "visibility": "hidden"},
                ]
            }
        )
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    models = get_codex_model_ids()

    assert models[0] == "gpt-5.2-codex"
    assert "gpt-5.1-codex" in models
    assert "gpt-5.3-codex" in models
    assert "gpt-5.3-codex-spark" in models
    assert "gpt-5.4" in models
    assert "gpt-5.4-mini" in models
    assert "gpt-5-hidden-codex" not in models


def test_setup_wizard_codex_import_resolves():
    """Regression test for the Codex model-list function name."""
    from hermes_cli.codex_models import get_codex_model_ids as setup_import

    assert callable(setup_import)


def test_get_codex_model_ids_falls_back_to_curated_defaults(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    models = get_codex_model_ids()

    assert models[: len(DEFAULT_CODEX_MODELS)] == DEFAULT_CODEX_MODELS
    assert "gpt-5.4" in models
    assert "gpt-5.3-codex-spark" in models


def test_get_codex_model_ids_adds_forward_compat_models_from_templates(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.codex_models._fetch_models_from_api",
        lambda access_token: ["gpt-5.3-codex"],
    )

    models = get_codex_model_ids(access_token="codex-access-token")

    assert models == [
        "gpt-5.3-codex",
        "gpt-5.5",
        "gpt-5.4-mini",
        "gpt-5.4",
        "gpt-5.3-codex-spark",
    ]


def test_fetch_from_api_keeps_supported_in_api_false_models(monkeypatch):
    """The OAuth-backed Codex route may serve models excluded from the public API."""
    import sys

    from hermes_cli import codex_models

    class _FakeResp:
        status_code = 200

        def json(self):
            return {
                "models": [
                    {"slug": "gpt-5.5", "priority": 0, "supported_in_api": True},
                    {
                        "slug": "gpt-5.3-codex-spark",
                        "priority": 7,
                        "supported_in_api": False,
                    },
                    {"slug": "gpt-5-internal", "priority": 99, "visibility": "hidden"},
                ]
            }

    class _FakeHttpx:
        @staticmethod
        def get(url, headers=None, timeout=None):
            return _FakeResp()

    monkeypatch.setitem(sys.modules, "httpx", _FakeHttpx)

    models = codex_models._fetch_models_from_api(access_token="tok")

    assert "gpt-5.5" in models
    assert "gpt-5.3-codex-spark" in models
    assert "gpt-5-internal" not in models


def test_only_codex_provider_profile_is_registered():
    from providers import get_provider_profile, list_providers

    profile = get_provider_profile("codex")

    assert profile is not None
    assert profile.name == "openai-codex"
    assert profile.api_mode == "codex_responses"
    assert [item.name for item in list_providers()] == ["openai-codex"]
    assert get_provider_profile("xai") is None
