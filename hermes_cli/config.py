"""Single-schema configuration for Hermes Lite."""

from __future__ import annotations

import copy
import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

from hermes_constants import get_config_path, get_env_path, get_hermes_home
from model_tools import DEFAULT_TOOL_NAMES

DEFAULT_CONFIG: dict[str, Any] = {
    "inference": {
        "model": "",
        "base_url": "",
        "api_key_env": "OPENAI_API_KEY",
        "temperature": 0.2,
    },
    "agent": {
        "max_iterations": 20,
        "system_prompt": "",
    },
    "tools": {
        "enabled": list(DEFAULT_TOOL_NAMES),
        "workspace": ".",
        "terminal": {
            "enabled": True,
            "confirm": True,
            "timeout_seconds": 60,
        },
    },
    "sessions": {
        "enabled": True,
        "resume_latest": False,
    },
    "logging": {
        "level": "WARNING",
        "file": True,
    },
}


class ConfigError(ValueError):
    """A malformed or unusable Hermes Lite configuration."""


def load_env_file(path: Path | None = None) -> None:
    """Load simple ``KEY=VALUE`` entries without overriding the process."""

    env_path = path or get_env_path()
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is None:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _merge_known(
    defaults: Mapping[str, Any],
    user_values: Mapping[str, Any],
    *,
    prefix: str,
    warn: Callable[[str], None] | None,
) -> dict[str, Any]:
    merged = copy.deepcopy(dict(defaults))
    for key, value in user_values.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in defaults:
            if warn:
                warn(f"ignoring unsupported config key: {path}")
            continue
        default = defaults[key]
        if isinstance(default, Mapping):
            if not isinstance(value, Mapping):
                raise ConfigError(f"{path} must be a mapping")
            merged[key] = _merge_known(default, value, prefix=path, warn=warn)
        else:
            merged[key] = value
    return merged


def _require_type(value: Any, expected: type | tuple[type, ...], path: str) -> None:
    expected_types = expected if isinstance(expected, tuple) else (expected,)
    if isinstance(value, bool) and any(item in {int, float} for item in expected_types):
        raise ConfigError(f"{path} has the wrong type")
    if not isinstance(value, expected):
        raise ConfigError(f"{path} has the wrong type")


def validate_config(config: Mapping[str, Any]) -> None:
    """Validate all supported fields and cross-field constraints."""

    inference = config["inference"]
    agent = config["agent"]
    tools = config["tools"]
    terminal = tools["terminal"]
    sessions = config["sessions"]
    logging_config = config["logging"]

    for key in ("model", "base_url", "api_key_env"):
        _require_type(inference[key], str, f"inference.{key}")
    _require_type(inference["temperature"], (int, float), "inference.temperature")
    if not 0 <= float(inference["temperature"]) <= 2:
        raise ConfigError("inference.temperature must be between 0 and 2")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", inference["api_key_env"]) is None:
        raise ConfigError("inference.api_key_env must be an environment variable name")

    _require_type(agent["max_iterations"], int, "agent.max_iterations")
    _require_type(agent["system_prompt"], str, "agent.system_prompt")
    if not 0 <= agent["max_iterations"] <= 100:
        raise ConfigError("agent.max_iterations must be between 0 and 100")

    _require_type(tools["enabled"], list, "tools.enabled")
    if any(not isinstance(name, str) or not name for name in tools["enabled"]):
        raise ConfigError("tools.enabled must contain only non-empty strings")
    if len(tools["enabled"]) != len(set(tools["enabled"])):
        raise ConfigError("tools.enabled must not contain duplicates")
    unknown_tools = sorted(set(tools["enabled"]) - set(DEFAULT_TOOL_NAMES))
    if unknown_tools:
        raise ConfigError(f"tools.enabled contains unsupported tools: {', '.join(unknown_tools)}")
    _require_type(tools["workspace"], str, "tools.workspace")
    if not tools["workspace"].strip():
        raise ConfigError("tools.workspace must not be empty")

    for key in ("enabled", "confirm"):
        _require_type(terminal[key], bool, f"tools.terminal.{key}")
    _require_type(terminal["timeout_seconds"], int, "tools.terminal.timeout_seconds")
    if not 1 <= terminal["timeout_seconds"] <= 300:
        raise ConfigError("tools.terminal.timeout_seconds must be between 1 and 300")

    for key in ("enabled", "resume_latest"):
        _require_type(sessions[key], bool, f"sessions.{key}")
    _require_type(logging_config["level"], str, "logging.level")
    _require_type(logging_config["file"], bool, "logging.file")
    if logging_config["level"].upper() not in {
        "CRITICAL",
        "ERROR",
        "WARNING",
        "INFO",
        "DEBUG",
    }:
        raise ConfigError("logging.level must be CRITICAL, ERROR, WARNING, INFO, or DEBUG")


def load_config(
    path: Path | None = None,
    *,
    warn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Load, filter, validate, and environment-override the configuration."""

    config_path = (path or get_config_path()).expanduser().resolve()
    user_values: Mapping[str, Any] = {}
    if config_path.exists():
        try:
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML in {config_path}: {exc}") from exc
        if loaded is not None and not isinstance(loaded, Mapping):
            raise ConfigError(f"configuration root must be a mapping: {config_path}")
        user_values = loaded or {}

    config = _merge_known(DEFAULT_CONFIG, user_values, prefix="", warn=warn)
    if os.environ.get("HERMES_MODEL"):
        config["inference"]["model"] = os.environ["HERMES_MODEL"]
    if os.environ.get("HERMES_BASE_URL"):
        config["inference"]["base_url"] = os.environ["HERMES_BASE_URL"]
    validate_config(config)
    return config


def write_default_config(
    path: Path | None = None,
    *,
    model: str = "",
    base_url: str = "",
    force: bool = False,
) -> Path:
    """Write a documented minimal config and return its path."""

    config_path = (path or get_config_path()).expanduser().resolve()
    if config_path.exists() and not force:
        raise ConfigError(f"configuration already exists: {config_path}")
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["inference"]["model"] = model
    config["inference"]["base_url"] = base_url
    validate_config(config)
    if path is None:
        get_hermes_home(create=True)
    config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    return config_path
