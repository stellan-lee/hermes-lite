"""Tests for config.yaml structure validation (validate_config_structure)."""


from hermes_cli.config import validate_config_structure, ConfigIssue




class TestFallbackProviderValidation:
    """fallback_providers is an ordered list of provider/model entries."""

    def test_missing_provider(self):
        issues = validate_config_structure({
            "fallback_providers": [{"model": "local-model"}],
        })
        assert any("missing 'provider'" in i.message for i in issues)

    def test_missing_model(self):
        issues = validate_config_structure({
            "fallback_providers": [{"provider": "custom"}],
        })
        assert any("missing 'model'" in i.message for i in issues)

    def test_valid_fallback(self):
        issues = validate_config_structure({
            "fallback_providers": [{
                "provider": "custom",
                "model": "local-model",
            }],
        })
        # Only fallback-related issues should be absent
        fb_issues = [i for i in issues if "fallback" in i.message.lower()]
        assert len(fb_issues) == 0

    def test_non_dict_fallback(self):
        issues = validate_config_structure({
            "fallback_providers": "custom:local-model",
        })
        assert any("should be a list" in i.message for i in issues)

    def test_empty_fallback_list_no_issues(self):
        issues = validate_config_structure({
            "fallback_providers": [],
        })
        fb_issues = [i for i in issues if "fallback" in i.message.lower()]
        assert len(fb_issues) == 0

    def test_valid_fallback_list(self):
        issues = validate_config_structure({
            "fallback_providers": [
                {"provider": "openai-codex", "model": "gpt-5.3-codex"},
                {"provider": "custom", "model": "local-model"},
            ],
        })
        fb_issues = [i for i in issues if "fallback" in i.message.lower()]
        assert len(fb_issues) == 0

    def test_fallback_list_entry_missing_provider(self):
        issues = validate_config_structure({
            "fallback_providers": [
                {"provider": "openai-codex", "model": "gpt-5.3-codex"},
                {"model": "local-model"},
            ],
        })
        assert any("fallback_providers[1]" in i.message and "provider" in i.message for i in issues)

    def test_fallback_list_entry_missing_model(self):
        issues = validate_config_structure({
            "fallback_providers": [
                {"provider": "custom"},
            ],
        })
        assert any("fallback_providers[0]" in i.message and "model" in i.message for i in issues)

    def test_fallback_list_entry_not_a_dict(self):
        issues = validate_config_structure({
            "fallback_providers": ["custom:local-model"],
        })
        assert any("fallback_providers[0]" in i.message and "should be a dict" in i.message for i in issues)


class TestMissingModelSection:
    """Warn when custom_providers exists but model section is missing."""


    def test_custom_providers_with_model(self):
        issues = validate_config_structure({
            "custom_providers": [
                {"name": "test", "base_url": "https://example.com/v1"},
            ],
            "model": {"provider": "custom", "default": "test-model"},
        })
        # Should not warn about missing model section
        assert not any("no 'model' section" in i.message for i in issues)


class TestConfigIssueDataclass:
    """ConfigIssue should be a proper dataclass."""

    def test_fields(self):
        issue = ConfigIssue(severity="error", message="test msg", hint="test hint")
        assert issue.severity == "error"
        assert issue.message == "test msg"
        assert issue.hint == "test hint"

    def test_equality(self):
        a = ConfigIssue("error", "msg", "hint")
        b = ConfigIssue("error", "msg", "hint")
        assert a == b
