"""Minimal profile type for the one retained OpenAI Codex provider."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderProfile:
    """Declarative fields consumed by the fixed Codex provider registry."""

    name: str
    aliases: tuple[str, ...] = ()
    api_mode: str = "codex_responses"
    env_vars: tuple[str, ...] = ()
    base_url: str = ""
    auth_type: str = "oauth_external"
