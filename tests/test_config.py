from __future__ import annotations

import pytest

from hermes_cli.config import (
    DEFAULT_CONFIG,
    ConfigError,
    load_config,
    load_env_file,
    validate_config,
    write_default_config,
)


def test_defaults_are_small_and_valid():
    config = load_config()
    assert tuple(config) == ("inference", "agent", "tools", "sessions", "logging")
    assert config == DEFAULT_CONFIG
    validate_config(config)


def test_unknown_legacy_keys_are_ignored_with_paths(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "memory:\n  provider: old\nagent:\n  max_iterations: 3\n  legacy: true\n",
        encoding="utf-8",
    )
    warnings: list[str] = []
    config = load_config(path, warn=warnings.append)
    assert config["agent"]["max_iterations"] == 3
    assert "memory" not in config
    assert warnings == [
        "ignoring unsupported config key: memory",
        "ignoring unsupported config key: agent.legacy",
    ]


@pytest.mark.parametrize(
    ("yaml_text", "message"),
    [
        ("[]\n", "root must be a mapping"),
        ("agent: false\n", "agent must be a mapping"),
        ("agent:\n  max_iterations: true\n", "agent.max_iterations has the wrong type"),
        ("tools:\n  terminal:\n    timeout_seconds: 0\n", "must be between 1 and 300"),
        ("tools:\n  enabled: [read_file, legacy]\n", "contains unsupported tools: legacy"),
        ("inference:\n  temperature: 9\n", "must be between 0 and 2"),
        ("inference:\n  api_key_env: BAD-NAME\n", "must be an environment variable name"),
        ("logging:\n  level: LOUD\n", "logging.level must be"),
    ],
)
def test_invalid_config_is_rejected(tmp_path, yaml_text, message):
    path = tmp_path / "config.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_environment_overrides_model_and_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_MODEL", "env-model")
    monkeypatch.setenv("HERMES_BASE_URL", "https://example.test/v1")
    config = load_config(tmp_path / "missing.yaml")
    assert config["inference"]["model"] == "env-model"
    assert config["inference"]["base_url"] == "https://example.test/v1"


def test_env_file_is_simple_and_does_not_override(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        "# comment\nOPENAI_API_KEY='from-file'\nINVALID-NAME=nope\nEXISTING=new\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EXISTING", "old")
    load_env_file(path)
    assert __import__("os").environ["OPENAI_API_KEY"] == "from-file"
    assert __import__("os").environ["EXISTING"] == "old"
    assert "INVALID-NAME" not in __import__("os").environ


def test_write_default_config_uses_explicit_path_only(tmp_path, isolated_hermes_home):
    path = tmp_path / "nested" / "config.yaml"
    written = write_default_config(path, model="model", base_url="https://host/v1")
    assert written == path
    assert not isolated_hermes_home.exists()
    loaded = load_config(path)
    assert loaded["inference"]["model"] == "model"
    assert loaded["inference"]["base_url"] == "https://host/v1"
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ConfigError, match="already exists"):
        write_default_config(path)


def test_every_default_leaf_is_loaded_from_yaml(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        """
inference:
  model: m
  base_url: https://host/v1
  api_key_env: CUSTOM_KEY
  temperature: 0.7
agent:
  max_iterations: 7
  system_prompt: custom
tools:
  enabled: [read_file]
  workspace: src
  terminal:
    enabled: false
    confirm: false
    timeout_seconds: 7
sessions:
  enabled: false
  resume_latest: true
logging:
  level: INFO
  file: false
""".lstrip(),
        encoding="utf-8",
    )
    config = load_config(path)
    assert config["inference"] == {
        "model": "m",
        "base_url": "https://host/v1",
        "api_key_env": "CUSTOM_KEY",
        "temperature": 0.7,
    }
    assert config["agent"] == {"max_iterations": 7, "system_prompt": "custom"}
    assert config["tools"]["terminal"] == {
        "enabled": False,
        "confirm": False,
        "timeout_seconds": 7,
    }
