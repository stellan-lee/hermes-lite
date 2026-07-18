"""Provider identity for Codex and user-defined compatible endpoints."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# -- Retained built-in provider metadata -------------------------------------

@dataclass(frozen=True)
class HermesOverlay:
    """Metadata for a retained built-in provider."""

    transport: str = "openai_chat"        # openai_chat | codex_responses
    is_aggregator: bool = False
    auth_type: str = "api_key"            # api_key | oauth_device_code | oauth_external | external_process
    extra_env_vars: Tuple[str, ...] = ()
    base_url_override: str = ""
    base_url_env_var: str = ""            # env var for user-custom base URL


HERMES_OVERLAYS: Dict[str, HermesOverlay] = {
    "openai-codex": HermesOverlay(
        transport="codex_responses",
        auth_type="oauth_external",
        base_url_override="https://chatgpt.com/backend-api/codex",
    ),
    "lmstudio": HermesOverlay(
        transport="openai_chat",
        extra_env_vars=("LM_API_KEY",),
        base_url_override="http://127.0.0.1:1234/v1",
        base_url_env_var="LM_BASE_URL",
    ),
}

# -- Resolved provider -------------------------------------------------------
# The merged result of built-in metadata or user config.

@dataclass
class ProviderDef:
    """Complete provider definition — merged from all sources."""

    id: str
    name: str
    transport: str                        # openai_chat | codex_responses
    api_key_env_vars: Tuple[str, ...]     # all env vars to check for API key
    base_url: str = ""
    base_url_env_var: str = ""
    is_aggregator: bool = False
    auth_type: str = "api_key"
    doc: str = ""
    source: str = ""                      # "hermes" | "user-config"


# -- Aliases ------------------------------------------------------------------
# Maps local shorthand to retained provider IDs.

ALIASES: Dict[str, str] = {
    "codex": "openai-codex",
    "lm-studio": "lmstudio",
    "lm_studio": "lmstudio",
    "ollama": "custom",
    "vllm": "custom",
    "llamacpp": "custom",
    "llama.cpp": "custom",
    "llama-cpp": "custom",
}

# -- Display labels -----------------------------------------------------------
# Labels for retained providers and generic compatible endpoints.

_LABEL_OVERRIDES: Dict[str, str] = {
    "openai-codex": "OpenAI Codex",
    "lmstudio": "LM Studio",
    "local": "Local endpoint",
    "custom": "Custom endpoint",
}

# -- Transport → API mode mapping ---------------------------------------------

TRANSPORT_TO_API_MODE: Dict[str, str] = {
    "openai_chat": "chat_completions",
    "codex_responses": "codex_responses",
}


# -- Helper functions ---------------------------------------------------------

def normalize_provider(name: str) -> str:
    """Resolve aliases and normalise casing to a canonical provider id.

    Returns the canonical id string.  Does *not* validate that the id
    corresponds to a known provider.
    """
    key = name.strip().lower()
    return ALIASES.get(key, key)


def get_provider(name: str) -> Optional[ProviderDef]:
    """Look up a retained built-in provider by id or alias."""
    canonical = normalize_provider(name)
    overlay = HERMES_OVERLAYS.get(canonical)
    if overlay is None:
        return None
    return ProviderDef(
        id=canonical,
        name=_LABEL_OVERRIDES.get(canonical, canonical),
        transport=overlay.transport,
        api_key_env_vars=overlay.extra_env_vars,
        base_url=overlay.base_url_override,
        base_url_env_var=overlay.base_url_env_var,
        is_aggregator=overlay.is_aggregator,
        auth_type=overlay.auth_type,
        source="hermes",
    )


def get_label(provider_id: str) -> str:
    """Get a human-readable display name for a provider."""
    canonical = normalize_provider(provider_id)

    # Check label overrides first
    if canonical in _LABEL_OVERRIDES:
        return _LABEL_OVERRIDES[canonical]

    pdef = get_provider(canonical)
    if pdef:
        return pdef.name

    return canonical




def is_aggregator(provider: str) -> bool:
    """Return True when the provider is a multi-model aggregator."""
    pdef = get_provider(provider)
    return pdef.is_aggregator if pdef else False


def determine_api_mode(provider: str, base_url: str = "") -> str:
    """Use Responses for Codex and Chat Completions for local endpoints."""
    del base_url
    pdef = get_provider(provider)
    if pdef is not None:
        return TRANSPORT_TO_API_MODE.get(pdef.transport, "chat_completions")
    return "chat_completions"


# -- Provider from user config ------------------------------------------------

def resolve_user_provider(name: str, user_config: Dict[str, Any]) -> Optional[ProviderDef]:
    """Resolve a provider from the user's config.yaml ``providers:`` section.

    Args:
        name: Provider name as given by the user.
        user_config: The ``providers:`` dict from config.yaml.

    Returns:
        ProviderDef if found, else None.
    """
    if not user_config or not isinstance(user_config, dict):
        return None

    entry = user_config.get(name)
    if not isinstance(entry, dict):
        return None

    # Extract fields
    display_name = entry.get("name", "") or name
    api_url = entry.get("base_url", "") or ""
    key_env = entry.get("key_env", "") or ""
    api_mode = entry.get("api_mode", "chat_completions") or "chat_completions"
    transport = "codex" if api_mode == "codex_responses" else "openai_chat"

    env_vars: List[str] = []
    if key_env:
        env_vars.append(key_env)

    return ProviderDef(
        id=name,
        name=display_name,
        transport=transport,
        api_key_env_vars=tuple(env_vars),
        base_url=api_url,
        is_aggregator=False,
        auth_type="api_key",
        source="user-config",
    )


def resolve_provider_full(
    name: str,
    user_providers: Optional[Dict[str, Any]] = None,
) -> Optional[ProviderDef]:
    """Resolve a retained built-in or canonical user provider.

    This is the main entry point for --provider flag resolution.

    Args:
        name: Provider name or alias.
        user_providers: The ``providers:`` dict from config.yaml (optional).
    Returns:
        ProviderDef if found, else None.
    """
    canonical = normalize_provider(name)
    raw = name.strip().lower()

    # 0. User-defined config providers win over the built-in alias table.
    #    A user who declares ``providers.<name>`` in config.yaml has stated
    #    explicit intent for that name — it must not be hijacked by a legacy
    #    explicit intent for that name. Resolve the raw name first.
    if user_providers:
        user_pdef = resolve_user_provider(raw, user_providers)
        if user_pdef is not None:
            return user_pdef

    # 1. Retained built-ins
    pdef = get_provider(canonical)
    if pdef is not None:
        return pdef

    # 2. User-defined providers from config
    if user_providers:
        # Try canonical name
        user_pdef = resolve_user_provider(canonical, user_providers)
        if user_pdef is not None:
            return user_pdef
        # Try original name (in case alias didn't match)
        user_pdef = resolve_user_provider(raw, user_providers)
        if user_pdef is not None:
            return user_pdef

    return None
