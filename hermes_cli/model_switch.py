"""Shared model-switching logic for CLI and gateway /model commands.

Both the CLI (cli.py) and gateway (gateway/run.py) /model handlers
share the same core pipeline:

  parse flags -> provider resolution ->
  credential resolution -> normalize model name ->
  metadata lookup -> build result

This module ties together retained provider identity, model normalization, and
runtime credential resolution.

Provider switching uses the ``--provider`` flag exclusively.
Provider switching uses ``--provider``; colons remain available to endpoint
model identifiers.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, NamedTuple, Optional

from hermes_cli.providers import (
    determine_api_mode,
    get_label,
    resolve_provider_full,
)
from hermes_cli.model_normalize import (
    normalize_model_for_provider,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model aliases -- short names -> (vendor, family) with NO version numbers.
# Resolved against the retained provider catalog.
# ---------------------------------------------------------------------------

class ModelIdentity(NamedTuple):
    """Vendor slug and family prefix used for catalog resolution."""
    vendor: str
    family: str


MODEL_ALIASES: dict[str, ModelIdentity] = {
    "gpt5":      ModelIdentity("openai-codex", "gpt-5"),
    "codex":     ModelIdentity("openai-codex", "gpt-"),
}


# ---------------------------------------------------------------------------
# Direct aliases — exact model+provider+base_url for custom/local servers.
# Checked BEFORE catalog resolution.  Format:
#   alias -> (model_id, provider, base_url)
# These can also be loaded from config.yaml ``model_aliases:`` section.
# ---------------------------------------------------------------------------

class DirectAlias(NamedTuple):
    """Exact model mapping that bypasses catalog resolution."""
    model: str
    provider: str
    base_url: str


# Built-in direct aliases (can be extended via config.yaml model_aliases:)
_BUILTIN_DIRECT_ALIASES: dict[str, DirectAlias] = {}

# Merged dict (builtins + user config); populated by _load_direct_aliases()
DIRECT_ALIASES: dict[str, DirectAlias] = {}


def _load_direct_aliases() -> dict[str, DirectAlias]:
    """Load direct aliases from config.yaml ``model_aliases:`` section.

    Config format::

        model_aliases:
          qwen:
            model: "qwen3.5:397b"
            provider: custom
            base_url: "https://ollama.com/v1"
    Also reads ``model.aliases`` (set by ``hermes config set model.aliases.xxx``)
    and converts simple string entries
    into DirectAlias objects.  The provider is parsed from the ``provider/``
    prefix in the value; if no slash, the current provider is used.
    """
    merged = dict(_BUILTIN_DIRECT_ALIASES)
    try:
        from hermes_cli.config import load_config
        cfg = load_config()

        # --- model_aliases (dict-based format) ---
        user_aliases = cfg.get("model_aliases")
        if isinstance(user_aliases, dict):
            for name, entry in user_aliases.items():
                if not isinstance(entry, dict):
                    continue
                model = entry.get("model", "")
                provider = entry.get("provider", "custom")
                base_url = entry.get("base_url", "")
                if model:
                    merged[name.strip().lower()] = DirectAlias(
                        model=model, provider=provider, base_url=base_url,
                    )

        # --- model.aliases (string-based format, from config set) ---
        model_section = cfg.get("model", {})
        if isinstance(model_section, dict):
            simple_aliases = model_section.get("aliases")
            if isinstance(simple_aliases, dict):
                current_provider = model_section.get("provider", "")
                for name, value in simple_aliases.items():
                    if not isinstance(value, str) or not value.strip():
                        continue
                    key = name.strip().lower()
                    if key in merged:
                        continue  # don't override explicit model_aliases entries
                    val = value.strip()
                    if "/" in val:
                        provider, model = val.split("/", 1)
                    else:
                        provider = current_provider
                        model = val
                    merged[key] = DirectAlias(
                        model=model.strip(),
                        provider=provider.strip() or current_provider,
                        base_url="",
                    )
    except Exception:
        pass
    return merged


def _ensure_direct_aliases() -> None:
    """Lazy-load direct aliases on first use.

    Mutates the existing DIRECT_ALIASES dict in place rather than rebinding
    the module attribute. This keeps `from hermes_cli.model_switch import
    DIRECT_ALIASES` references valid in callers — rebinding would leave them
    pointing at a stale empty dict.
    """
    if not DIRECT_ALIASES:
        DIRECT_ALIASES.update(_load_direct_aliases())


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ModelSwitchResult:
    """Result of a model switch attempt."""

    success: bool
    new_model: str = ""
    target_provider: str = ""
    provider_changed: bool = False
    api_key: str = ""
    base_url: str = ""
    api_mode: str = ""
    error_message: str = ""
    warning_message: str = ""
    provider_label: str = ""
    resolved_via_alias: str = ""
    is_global: bool = False
# ---------------------------------------------------------------------------
# Flag parsing
# ---------------------------------------------------------------------------

def parse_model_flags(raw_args: str) -> tuple[str, str, bool, bool]:
    """Parse --provider, --global, and --refresh flags from /model command args.

    Returns (model_input, explicit_provider, is_global, force_refresh).

    Examples::

        "sonnet"                         -> ("sonnet", "", False, False)
        "sonnet --global"                -> ("sonnet", "", True, False)
        "qwen --provider local"          -> ("qwen", "local", False, False)
        "--provider my-ollama"           -> ("", "my-ollama", False, False)
        "--refresh"                      -> ("", "", False, True)
        "qwen --provider local --global" -> ("qwen", "local", True, False)
    """
    is_global = False
    explicit_provider = ""
    force_refresh = False

    # Normalize Unicode dashes (Telegram/iOS auto-converts -- to em/en dash)
    # A single Unicode dash before a flag keyword becomes "--"
    import re as _re
    raw_args = _re.sub(r'[\u2012\u2013\u2014\u2015](provider|global|refresh)', r'--\1', raw_args)

    # Extract --global
    if "--global" in raw_args:
        is_global = True
        raw_args = raw_args.replace("--global", "").strip()

    # Extract --refresh (bust the model picker disk cache before listing)
    if "--refresh" in raw_args:
        force_refresh = True
        raw_args = raw_args.replace("--refresh", "").strip()

    # Extract --provider <name>
    parts = raw_args.split()
    i = 0
    filtered: list[str] = []
    while i < len(parts):
        if parts[i] == "--provider" and i + 1 < len(parts):
            explicit_provider = parts[i + 1]
            i += 2
        else:
            filtered.append(parts[i])
            i += 1

    model_input = " ".join(filtered).strip()
    return (model_input, explicit_provider, is_global, force_refresh)


# ---------------------------------------------------------------------------
# Alias resolution
# ---------------------------------------------------------------------------

def _model_sort_key(model_id: str, prefix: str) -> tuple:
    """Sort key for model version preference.

    Extracts version numbers after the family prefix and returns a sort key
    that prefers higher versions.  Suffix tokens (``pro``, ``omni``, etc.)
    are used as tiebreakers, with common quality indicators ranked.

    Examples (with prefix ``"mimo"``)::

        mimo-v2.5-pro   → (-2.5, 0, 'pro')     # highest version wins
        mimo-v2.5       → (-2.5, 1, '')          # no suffix = lower than pro
        mimo-v2-pro     → (-2.0, 0, 'pro')
        mimo-v2-omni    → (-2.0, 1, 'omni')
        mimo-v2-flash   → (-2.0, 1, 'flash')
    """
    # Strip the prefix (and optional "/" separator for aggregator slugs)
    rest = model_id[len(prefix):]
    if rest.startswith("/"):
        rest = rest[1:]
    rest = rest.lstrip("-").strip()

    # Parse version and suffix from the remainder.
    # "v2.5-pro" → version [2.5], suffix "pro"
    # "-omni"    → version [],    suffix "omni"
    # State machine: start → in_version → between → in_suffix
    nums: list[float] = []
    suffix_buf = ""
    state = "start"
    num_buf = ""

    for ch in rest:
        if state == "start":
            if ch in "vV":
                state = "in_version"
            elif ch.isdigit():
                state = "in_version"
                num_buf += ch
            elif ch in "-_.":
                pass  # skip separators before any content
            else:
                state = "in_suffix"
                suffix_buf += ch
        elif state == "in_version":
            if ch.isdigit():
                num_buf += ch
            elif ch == ".":
                if "." in num_buf:
                    # Second dot — flush current number, start new component
                    try:
                        nums.append(float(num_buf.rstrip(".")))
                    except ValueError:
                        pass
                    num_buf = ""
                else:
                    num_buf += ch
            elif ch in "-_.":
                if num_buf:
                    try:
                        nums.append(float(num_buf.rstrip(".")))
                    except ValueError:
                        pass
                    num_buf = ""
                state = "between"
            else:
                if num_buf:
                    try:
                        nums.append(float(num_buf.rstrip(".")))
                    except ValueError:
                        pass
                    num_buf = ""
                state = "in_suffix"
                suffix_buf += ch
        elif state == "between":
            if ch.isdigit():
                state = "in_version"
                num_buf = ch
            elif ch in "vV":
                state = "in_version"
            elif ch in "-_.":
                pass
            else:
                state = "in_suffix"
                suffix_buf += ch
        elif state == "in_suffix":
            suffix_buf += ch

    # Flush remaining buffer (strip trailing dots — "5.4." → "5.4")
    if num_buf and state == "in_version":
        try:
            nums.append(float(num_buf.rstrip(".")))
        except ValueError:
            pass

    suffix = suffix_buf.lower().strip("-_.")
    suffix = suffix.strip()

    # Negate versions so higher → sorts first
    version_key = tuple(-n for n in nums)

    # Suffix quality ranking: pro/max > (no suffix) > omni/flash/mini/lite
    # Lower number = preferred
    _SUFFIX_RANK = {"pro": 0, "max": 0, "plus": 0, "turbo": 0}
    suffix_rank = _SUFFIX_RANK.get(suffix, 1)

    return version_key + (suffix_rank, suffix)


def resolve_alias(
    raw_input: str,
    current_provider: str,
) -> Optional[tuple[str, str, str]]:
    """Resolve a short alias against the current provider's catalog.

    Looks up *raw_input* in :data:`MODEL_ALIASES`, then searches the retained
    provider's static/live catalog for the highest matching version.

    Returns:
        ``(provider, resolved_model_id, alias_name)`` if a match is
        found on the current provider, or ``None`` if the alias doesn't
        exist or no matching model is available.
    """
    key = raw_input.strip().lower()

    # Check direct aliases first (exact model+provider+base_url mappings)
    _ensure_direct_aliases()
    direct = DIRECT_ALIASES.get(key)
    if direct is not None:
        return (direct.provider, direct.model, key)

    # Reverse lookup lets a configured full model ID reuse a direct alias.
    for alias_name, da in DIRECT_ALIASES.items():
        if da.model.lower() == key:
            return (da.provider, da.model, alias_name)

    identity = MODEL_ALIASES.get(key)
    if identity is None:
        return None

    _vendor, family = identity

    # Resolve aliases against the small retained static catalog.
    catalog: list[str] = []
    try:
        from hermes_cli.models import _PROVIDER_MODELS
        static = _PROVIDER_MODELS.get(current_provider, [])
        catalog.extend(static)
    except Exception:
        pass

    family_lower = family.lower()
    matches = [mid for mid in catalog if mid.lower().startswith(family_lower)]

    if not matches:
        return None

    # Sort by version descending — prefer the latest/highest version
    matches.sort(key=lambda m: _model_sort_key(m, family))
    return (current_provider, matches[0], key)


def get_authenticated_provider_slugs(
    current_provider: str = "",
    user_providers: dict = None,
    custom_providers: list | None = None,
) -> list[str]:
    """Return slugs of providers that have credentials.

    Uses ``list_authenticated_providers()`` and its retained endpoint cache.
    """
    try:
        providers = list_authenticated_providers(
            current_provider=current_provider,
            user_providers=user_providers,
            custom_providers=custom_providers,
            max_models=0,
        )
        return [p["slug"] for p in providers]
    except Exception:
        return []


def _resolve_alias_fallback(
    raw_input: str,
    authenticated_providers: list[str] = (),
) -> Optional[tuple[str, str, str]]:
    """Try to resolve an alias on the user's authenticated providers.

    Only authenticated retained providers participate.
    """
    for provider in authenticated_providers:
        result = resolve_alias(raw_input, provider)
        if result is not None:
            return result
    return None


def resolve_display_context_length(
    model: str,
    provider: str,
    base_url: str = "",
    api_key: str = "",
    custom_providers: list | None = None,
    config_context_length: int | None = None,
) -> Optional[int]:
    """Resolve the context length to show in /model output.

    Provider-enforced context limits can differ by transport. The authoritative source is
    ``agent.model_metadata.get_model_context_length`` which already knows
    about Codex OAuth and configured custom/local endpoints.

    When ``custom_providers`` is provided, per-model ``context_length``
    overrides from ``custom_providers[].models.<id>.context_length`` are
    honored — this closes #15779 where ``/model`` switch ignored user-set
    overrides.

    The provider-aware resolver is the sole source of context length.
    """
    try:
        from agent.model_metadata import get_model_context_length
        ctx = get_model_context_length(
            model,
            base_url=base_url or "",
            api_key=api_key or "",
            provider=provider or None,
            custom_providers=custom_providers,
            config_context_length=config_context_length,
        )
        if ctx:
            return int(ctx)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Core model-switching pipeline
# ---------------------------------------------------------------------------

def switch_model(
    raw_input: str,
    current_provider: str,
    current_model: str,
    current_base_url: str = "",
    current_api_key: str = "",
    is_global: bool = False,
    explicit_provider: str = "",
    user_providers: dict = None,
    custom_providers: list | None = None,
) -> ModelSwitchResult:
    """Switch between Codex and configured compatible endpoints."""
    import os

    from hermes_cli.models import validate_requested_model
    from hermes_cli.runtime_provider import resolve_runtime_provider

    new_model = raw_input.strip()
    requested_provider = explicit_provider.strip() or current_provider
    pdef = resolve_provider_full(
        requested_provider,
        user_providers,
    )
    if pdef is None:
        return ModelSwitchResult(
            success=False,
            is_global=is_global,
            error_message=(
                f"Unknown provider '{requested_provider}'. Define custom endpoints "
                "under providers: in config.yaml."
            ),
        )

    target_provider = pdef.id
    provider_label = pdef.name or get_label(target_provider)
    provider_changed = target_provider != current_provider

    if not new_model:
        if not pdef.base_url:
            return ModelSwitchResult(
                success=False,
                target_provider=target_provider,
                provider_label=provider_label,
                is_global=is_global,
                error_message=f"Provider '{provider_label}' has no model configured.",
            )
        try:
            from hermes_cli.runtime_provider import _auto_detect_local_model

            new_model = _auto_detect_local_model(pdef.base_url) or ""
        except Exception:
            new_model = ""
        if not new_model:
            return ModelSwitchResult(
                success=False,
                target_provider=target_provider,
                provider_label=provider_label,
                is_global=is_global,
                error_message=(
                    f"Could not detect a model for '{provider_label}'. "
                    "Specify one explicitly."
                ),
            )

    api_key = current_api_key
    base_url = current_base_url
    api_mode = ""

    user_cfg = None
    if isinstance(user_providers, dict):
        user_cfg = user_providers.get(explicit_provider) or user_providers.get(
            target_provider
        )
    explicit_key = ""
    if isinstance(user_cfg, dict):
        explicit_key = str(user_cfg.get("api_key") or "").strip()
        if explicit_key.startswith("${") and explicit_key.endswith("}"):
            explicit_key = os.getenv(explicit_key[2:-1], "").strip()
        if not explicit_key:
            key_env = str(user_cfg.get("key_env") or "").strip()
            if key_env:
                explicit_key = os.getenv(key_env, "").strip()

    should_resolve = bool(explicit_provider or provider_changed)
    if should_resolve:
        try:
            runtime = resolve_runtime_provider(
                requested=target_provider,
                explicit_api_key=explicit_key or None,
                explicit_base_url=pdef.base_url or None,
                target_model=new_model,
            )
            api_key = runtime.get("api_key", "") or explicit_key
            base_url = runtime.get("base_url", "") or pdef.base_url
            api_mode = runtime.get("api_mode", "")
        except Exception as exc:
            return ModelSwitchResult(
                success=False,
                target_provider=target_provider,
                provider_label=provider_label,
                is_global=is_global,
                error_message=(
                    f"Could not resolve credentials for '{provider_label}': {exc}"
                ),
            )
    else:
        api_mode = determine_api_mode(target_provider, base_url)

    new_model = normalize_model_for_provider(new_model, target_provider)
    if not api_mode:
        api_mode = determine_api_mode(target_provider, base_url)

    try:
        validation = validate_requested_model(
            new_model,
            target_provider,
            api_key=api_key,
            base_url=base_url,
            api_mode=api_mode or None,
        )
    except Exception as exc:
        validation = {
            "accepted": False,
            "message": f"Could not validate `{new_model}`: {exc}",
        }

    if not validation.get("accepted"):
        declared = False
        if isinstance(user_cfg, dict):
            models = user_cfg.get("models") or {}
            declared = new_model == user_cfg.get("model") or new_model in models
        if not declared:
            return ModelSwitchResult(
                success=False,
                new_model=new_model,
                target_provider=target_provider,
                provider_label=provider_label,
                is_global=is_global,
                error_message=validation.get("message") or "Invalid model",
            )

    if validation.get("corrected_model"):
        new_model = validation["corrected_model"]

    warning = validation.get("message") or ""
    return ModelSwitchResult(
        success=True,
        new_model=new_model,
        target_provider=target_provider,
        provider_changed=provider_changed,
        api_key=api_key,
        base_url=base_url,
        api_mode=api_mode,
        warning_message=warning,
        provider_label=provider_label,
        is_global=is_global,
    )


# ---------------------------------------------------------------------------
# Authenticated providers listing (for /model no-args display)
# ---------------------------------------------------------------------------

def list_authenticated_providers(
    current_provider: str = "",
    current_base_url: str = "",
    user_providers: dict = None,
    custom_providers: list | None = None,
    max_models: int = 8,
    current_model: str = "",
) -> List[dict]:
    """List configured Codex and custom/local model endpoints."""
    import os

    from hermes_cli.models import cached_provider_model_ids

    results: List[dict] = []
    seen_slugs: set[str] = set()
    codex_configured = current_provider == "openai-codex"
    if not codex_configured:
        try:
            from hermes_cli.auth import _load_auth_store

            provider_data = (_load_auth_store().get("providers") or {}).get(
                "openai-codex", {}
            )
            tokens = provider_data.get("tokens") or {}
            codex_configured = bool(tokens.get("access_token"))
        except Exception:
            codex_configured = False
    if codex_configured:
        codex_models = cached_provider_model_ids("openai-codex")
        results.append(
            {
                "slug": "openai-codex",
                "name": "OpenAI Codex",
                "is_current": current_provider == "openai-codex",
                "is_user_defined": False,
                "models": codex_models[:max_models] if max_models else codex_models,
                "total_models": len(codex_models),
                "source": "codex",
            }
        )
        seen_slugs.add("openai-codex")

    lmstudio_configured = bool(
        os.getenv("LM_BASE_URL")
        or os.getenv("LM_API_KEY")
        or current_provider == "lmstudio"
    )
    if lmstudio_configured:
        from hermes_cli.models import fetch_lmstudio_models

        lmstudio_url = (
            os.getenv("LM_BASE_URL")
            or current_base_url
            or "http://127.0.0.1:1234/v1"
        )
        lmstudio_models = fetch_lmstudio_models(
            api_key=os.getenv("LM_API_KEY") or None,
            base_url=lmstudio_url,
        )
        if current_model and current_model not in lmstudio_models:
            lmstudio_models.insert(0, current_model)
        results.append(
            {
                "slug": "lmstudio",
                "name": "LM Studio",
                "is_current": current_provider == "lmstudio",
                "is_user_defined": True,
                "models": lmstudio_models[:max_models] if max_models else lmstudio_models,
                "total_models": len(lmstudio_models),
                "source": "local",
                "api_url": lmstudio_url,
            }
        )
        seen_slugs.add("lmstudio")

    # --- 3. User-defined endpoints from canonical config ---
    if user_providers and isinstance(user_providers, dict):
        for ep_name, ep_cfg in user_providers.items():
            if not isinstance(ep_cfg, dict):
                continue
            # Skip if this slug was already emitted (e.g. canonical provider
            # with the same name) or will be picked up by section 4.
            if ep_name.lower() in seen_slugs:
                continue
            display_name = ep_cfg.get("name", "") or ep_name
            api_url = ep_cfg.get("base_url", "") or ""
            default_model = ep_cfg.get("model", "")

            # Build models list from both default_model and full models array
            models_list = []
            if default_model:
                models_list.append(default_model)
            # Include configured per-model entries.
            cfg_models = ep_cfg.get("models", [])
            if isinstance(cfg_models, dict):
                for m in cfg_models:
                    if m and m not in models_list:
                        models_list.append(m)

            # Prefer the endpoint's live /models list when credentials are
            # available, unless the provider explicitly opts out via
            # discover_models: false (e.g. dedicated endpoints that expose
            # the entire aggregator catalog via /models).
            api_key = str(ep_cfg.get("api_key", "") or "").strip()
            if not api_key:
                key_env = str(ep_cfg.get("key_env", "") or "").strip()
                api_key = os.environ.get(key_env, "").strip() if key_env else ""
            discover = ep_cfg.get("discover_models", True)
            if isinstance(discover, str):
                discover = discover.lower() not in {"false", "no", "0"}
            should_probe = bool(api_url) and discover and (
                bool(api_key) or not models_list
            )
            if should_probe:
                try:
                    from hermes_cli.models import fetch_api_models
                    live_models = fetch_api_models(api_key, api_url)
                    if live_models:
                        models_list = live_models
                except Exception:
                    pass

            results.append({
                "slug": ep_name,
                "name": display_name,
                "is_current": ep_name == current_provider,
                "is_user_defined": True,
                "models": models_list,
                "total_models": len(models_list) if models_list else 0,
                "source": "user-config",
                "api_url": api_url,
            })
            seen_slugs.add(ep_name.lower())

    # Sort: current provider first, then by model count descending
    results.sort(key=lambda r: (not r["is_current"], -r["total_models"]))

    return results


def list_picker_providers(
    current_provider: str = "",
    current_base_url: str = "",
    user_providers: dict = None,
    custom_providers: list | None = None,
    max_models: int = 8,
    current_model: str = "",
) -> List[dict]:
    """Interactive-picker variant of :func:`list_authenticated_providers`.

    Rows whose model list is empty are dropped, except
      custom endpoints (``is_user_defined=True`` with an ``api_url``) where
      the user may supply their own model set through config.
    """
    providers = list_authenticated_providers(
        current_provider=current_provider,
        current_base_url=current_base_url,
        user_providers=user_providers,
        custom_providers=custom_providers,
        max_models=max_models,
        current_model=current_model,
    )

    filtered: List[dict] = []
    for p in providers:
        has_models = bool(p.get("models"))
        is_custom_endpoint = bool(p.get("is_user_defined")) and bool(p.get("api_url"))
        if not has_models and not is_custom_endpoint:
            continue
        filtered.append(p)

    return filtered
