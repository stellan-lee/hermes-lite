"""Fixed provider registry for the retained OpenAI Codex profile."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from providers.base import ProviderProfile

_REGISTRY: dict[str, ProviderProfile] = {}
_ALIASES: dict[str, str] = {}
_discovered = False


def register_provider(profile: ProviderProfile) -> None:
    """Register the fixed Codex profile by name and aliases."""

    _REGISTRY[profile.name] = profile
    for alias in profile.aliases:
        _ALIASES[alias] = profile.name


def _load_codex_profile() -> None:
    """Load only the bundled Codex profile; no plugin discovery is performed."""

    global _discovered
    if _discovered:
        return
    _discovered = True

    profile_dir = (
        Path(__file__).resolve().parent.parent / "plugins" / "model-providers" / "openai-codex"
    )
    init_file = profile_dir / "__init__.py"
    if not init_file.is_file():
        return

    module_name = "plugins.model_providers.openai_codex"
    spec = importlib.util.spec_from_file_location(
        module_name,
        init_file,
        submodule_search_locations=[str(profile_dir)],
    )
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)


def get_provider_profile(name: str) -> ProviderProfile | None:
    """Return the retained Codex profile by canonical name or alias."""

    _load_codex_profile()
    return _REGISTRY.get(_ALIASES.get(name, name))


def list_providers() -> list[ProviderProfile]:
    """Return the single fixed provider catalog."""

    _load_codex_profile()
    return list(_REGISTRY.values())
