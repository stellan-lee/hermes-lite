"""Filesystem locations for Hermes Lite."""

from __future__ import annotations

import os
from pathlib import Path


def get_hermes_home(*, create: bool = False) -> Path:
    """Return the Hermes data directory.

    ``HERMES_HOME`` is the only supported location override. Profiles and
    distribution-specific homes were intentionally removed from Hermes Lite.
    """

    configured = os.environ.get("HERMES_HOME")
    home = Path(configured).expanduser() if configured else Path.home() / ".hermes"
    home = home.resolve()
    if create:
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
    return home


def display_hermes_home() -> str:
    """Return a user-facing representation of the Hermes data directory."""

    return str(get_hermes_home())


def get_config_path() -> Path:
    """Return the configured YAML path without creating it."""

    configured = os.environ.get("HERMES_CONFIG")
    if configured:
        return Path(configured).expanduser().resolve()
    return get_hermes_home() / "config.yaml"


def get_env_path() -> Path:
    """Return the optional per-user environment file path."""

    return get_hermes_home() / ".env"


def get_session_db_path() -> Path:
    """Return the Lite-specific session database path."""

    return get_hermes_home() / "sessions-lite.db"


def get_log_path() -> Path:
    """Return the single runtime log path."""

    return get_hermes_home() / "hermes-lite.log"
