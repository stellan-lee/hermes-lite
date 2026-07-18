"""Security coverage for retained runtime and connector environment values."""

import os
from unittest.mock import patch

from tools.environments.local import (
    _MARLOW_PROVIDER_ENV_BLOCKLIST,
    _MARLOW_PROVIDER_ENV_FORCE_PREFIX,
    _sanitize_subprocess_env,
)


RETAINED_SECRETS = {
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "BRAVE_SEARCH_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "DISCORD_BOT_TOKEN",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "FEISHU_APP_SECRET",
    "EMAIL_PASSWORD",
    "WEBHOOK_SECRET",
    "HONCHO_API_KEY",
    "MARLOW_LANGFUSE_SECRET_KEY",
}


def test_retained_secrets_are_blocklisted():
    assert RETAINED_SECRETS.issubset(_MARLOW_PROVIDER_ENV_BLOCKLIST)


def test_retained_secrets_are_stripped_from_children():
    base = {name: "secret" for name in RETAINED_SECRETS}
    base.update({"PATH": "/usr/bin:/bin", "HOME": "/home/user"})
    with patch.dict(os.environ, base, clear=True):
        result = _sanitize_subprocess_env(dict(os.environ))
    assert RETAINED_SECRETS.isdisjoint(result)
    assert result["PATH"] == "/usr/bin:/bin"
    assert result["HOME"] == "/home/user"


def test_force_prefix_explicitly_passes_blocked_value():
    forced = f"{_MARLOW_PROVIDER_ENV_FORCE_PREFIX}OPENAI_API_KEY"
    result = _sanitize_subprocess_env({}, {forced: "explicit"})
    assert result["OPENAI_API_KEY"] == "explicit"
    assert forced not in result
