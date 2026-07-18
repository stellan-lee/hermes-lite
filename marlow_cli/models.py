"""
Canonical model catalogs and lightweight validation helpers.

Add, remove, or reorder entries here — both `marlow setup` and
`marlow` provider-selection will pick up the change automatically.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
import time
from difflib import get_close_matches
from pathlib import Path
from typing import Any, NamedTuple, Optional

from marlow_cli import __version__ as _MARLOW_VERSION

# Identify ourselves so endpoints fronted by Cloudflare's Browser Integrity
# Check (error 1010) don't reject the default ``Python-urllib/*`` signature.
_MARLOW_USER_AGENT = f"marlow-cli/{_MARLOW_VERSION}"


def _codex_curated_models() -> list[str]:
    """Derive the openai-codex curated list from codex_models.py.

    Single source of truth: DEFAULT_CODEX_MODELS + forward-compat synthesis.
    This keeps the gateway /model picker in sync with the CLI `marlow model`
    flow without maintaining a separate static list.
    """
    from marlow_cli.codex_models import DEFAULT_CODEX_MODELS, _add_forward_compat_models

    return _add_forward_compat_models(list(DEFAULT_CODEX_MODELS))


_PROVIDER_MODELS: dict[str, list[str]] = {
    "openai-codex": _codex_curated_models(),
    "lmstudio": [],
}


class ProviderEntry(NamedTuple):
    slug: str
    label: str
    tui_desc: str  # detailed description for `marlow model` TUI


CANONICAL_PROVIDERS: list[ProviderEntry] = [
    ProviderEntry(
        "lmstudio",
        "LM Studio",
        "LM Studio (Local desktop app with built-in model server)",
    ),
    ProviderEntry(
        "openai-codex",
        "OpenAI Codex",
        "OpenAI Codex (ChatGPT subscription via Codex OAuth)",
    ),
]

_canonical_slugs = {p.slug for p in CANONICAL_PROVIDERS}

# Derived dicts — used throughout the codebase
_PROVIDER_LABELS = {p.slug: p.label for p in CANONICAL_PROVIDERS}
_PROVIDER_LABELS["custom"] = "Custom endpoint"  # special case: not a named provider


_PROVIDER_ALIASES = {
    "codex": "openai-codex",
    "openai_codex": "openai-codex",
    "lm-studio": "lmstudio",
    "lm_studio": "lmstudio",
    "ollama": "custom",
    "vllm": "custom",
    "llamacpp": "custom",
    "llama.cpp": "custom",
    "llama-cpp": "custom",
    "local": "custom",
}
_KNOWN_PROVIDER_NAMES = _canonical_slugs | set(_PROVIDER_ALIASES) | {"custom"}


def get_default_model_for_provider(provider: str) -> str:
    """Return the default model for a provider, or empty string if unknown.

    Uses the first entry in _PROVIDER_MODELS as the default.  This is the
    model a user would be offered first in the ``marlow model`` picker.

    Used as a fallback when the user has configured a provider but never
    selected a model (e.g. ``marlow auth add openai-codex`` without
    ``marlow model``).
    """
    models = _PROVIDER_MODELS.get(provider, [])
    return models[0] if models else ""


def _format_price_per_mtok(per_token_str: str) -> str:
    """Format a per-token price as a per-million-token display value."""
    try:
        value = float(per_token_str) * 1_000_000
    except (TypeError, ValueError):
        return ""
    return "free" if value == 0 else f"${value:.2f}"


def get_pricing_for_provider(
    provider: str, *, force_refresh: bool = False
) -> dict[str, dict[str, str]]:
    """Codex subscription and local endpoints do not expose token pricing."""
    del provider, force_refresh
    return {}


def list_available_providers() -> list[dict[str, str]]:
    """Return info about all providers the user could use with ``provider:model``.

    Each dict has ``id``, ``label``, and ``aliases``.
    Checks which providers have valid credentials configured.

    Derives the provider list from :data:`CANONICAL_PROVIDERS` (single
    source of truth shared with ``marlow model``, ``/model``, etc.).
    """
    # Derive display order from canonical list + custom
    provider_order = [p.slug for p in CANONICAL_PROVIDERS] + ["custom"]

    # Build reverse alias map
    aliases_for: dict[str, list[str]] = {}
    for alias, canonical in _PROVIDER_ALIASES.items():
        aliases_for.setdefault(canonical, []).append(alias)

    result = []
    for pid in provider_order:
        label = _PROVIDER_LABELS.get(pid, pid)
        alias_list = aliases_for.get(pid, [])
        # Check if this provider has credentials available
        has_creds = False
        try:
            from marlow_cli.auth import get_auth_status, has_usable_secret

            if pid == "custom":
                custom_base_url = _get_custom_base_url() or ""
                has_creds = bool(custom_base_url.strip())
            else:
                status = get_auth_status(pid)
                has_creds = bool(status.get("logged_in") or status.get("configured"))
        except Exception:
            pass
        result.append({
            "id": pid,
            "label": label,
            "aliases": alias_list,
            "authenticated": has_creds,
        })
    return result


def parse_model_input(raw: str, current_provider: str) -> tuple[str, str]:
    """Parse ``/model`` input into ``(provider, model)``.

    Supports retained ``provider:model`` syntax, for example
    ``openai-codex:gpt-5.3-codex`` or ``custom:local:qwen``.

    The colon is only treated as a provider delimiter if the left side is a
    recognized provider name or alias, avoiding accidental splits in model IDs.

    Returns ``(provider, model)`` where *provider* is either the explicit
    provider from the input or *current_provider* if none was specified.
    """
    stripped = raw.strip()
    colon = stripped.find(":")
    if colon > 0:
        provider_part = stripped[:colon].strip().lower()
        model_part = stripped[colon + 1 :].strip()
        if provider_part and model_part and provider_part in _KNOWN_PROVIDER_NAMES:
            # Support custom:name:model triple syntax for named custom
            # providers.  ``custom:local:qwen`` → ("custom:local", "qwen").
            # Single colon ``custom:qwen`` → ("custom", "qwen") as before.
            if provider_part == "custom" and ":" in model_part:
                second_colon = model_part.find(":")
                custom_name = model_part[:second_colon].strip()
                actual_model = model_part[second_colon + 1 :].strip()
                if custom_name and actual_model:
                    return (f"custom:{custom_name}", actual_model)
            return (normalize_provider(provider_part), model_part)
    return (current_provider, stripped)


def _get_custom_base_url() -> str:
    """Get the custom endpoint base_url from config.yaml."""
    try:
        from marlow_cli.config import load_config

        config = load_config()
        model_cfg = config.get("model", {})
        if isinstance(model_cfg, dict):
            return str(model_cfg.get("base_url", "")).strip()
    except Exception:
        pass
    return ""


def curated_models_for_provider(
    provider: Optional[str],
    *,
    force_refresh: bool = False,
) -> list[tuple[str, str]]:
    """Return ``(model_id, description)`` tuples for a provider's model list.

    Tries to fetch the live model list from the provider's API first,
    falling back to the static ``_PROVIDER_MODELS`` catalog if the API
    is unreachable.
    """
    normalized = normalize_provider(provider)
    # Try live API first for retained providers.
    live = provider_model_ids(normalized)
    if live:
        return [(m, "") for m in live]

    # Fallback to static catalog
    models = _PROVIDER_MODELS.get(normalized, [])
    return [(m, "") for m in models]








def detect_static_provider_for_model(
    model_name: str, current_provider: str = ""
) -> Optional[tuple[str, str]]:
    """Recognize Codex models without guessing third-party providers."""
    requested = (model_name or "").strip()
    if not requested or normalize_provider(current_provider) == "openai-codex":
        return None
    codex_models = {m.lower(): m for m in _PROVIDER_MODELS.get("openai-codex", [])}
    match = codex_models.get(requested.lower())
    return ("openai-codex", match) if match else None


def detect_provider_for_model(
    model_name: str, current_provider: str
) -> Optional[tuple[str, str]]:
    """Return only confident Codex matches; custom endpoints stay explicit."""
    return detect_static_provider_for_model(model_name, current_provider)


def normalize_provider(provider: Optional[str]) -> str:
    """Normalize provider aliases to Marlow' canonical provider ids.

    Note: ``"auto"`` passes through unchanged — use
    ``marlow_cli.auth.resolve_provider()`` to resolve it to a concrete
    provider based on credentials and environment.
    """
    normalized = (provider or "auto").strip().lower()
    return _PROVIDER_ALIASES.get(normalized, normalized)


def provider_label(provider: Optional[str]) -> str:
    """Return a human-friendly label for a provider id or alias."""
    original = (provider or "auto").strip()
    normalized = original.lower()
    if normalized == "auto":
        return "Auto"
    normalized = normalize_provider(normalized)
    return _PROVIDER_LABELS.get(normalized, original or "Auto")


def provider_model_ids(
    provider: Optional[str], *, force_refresh: bool = False
) -> list[str]:
    """Return models for Codex, LM Studio, or a custom compatible endpoint."""
    del force_refresh
    normalized = normalize_provider(provider)
    if normalized == "openai-codex":
        from marlow_cli.codex_models import get_codex_model_ids

        access_token = None
        try:
            from marlow_cli.auth import resolve_codex_runtime_credentials

            access_token = resolve_codex_runtime_credentials().get("api_key")
        except Exception:
            pass
        return get_codex_model_ids(access_token=access_token)
    if normalized == "lmstudio":
        return fetch_lmstudio_models(
            api_key=os.getenv("LM_API_KEY") or None,
            base_url=os.getenv("LM_BASE_URL") or "http://127.0.0.1:1234/v1",
        )
    if normalized in {"custom", "local"}:
        base_url = _get_custom_base_url()
        return (
            fetch_api_models(os.getenv("CUSTOM_API_KEY", ""), base_url)
            if base_url
            else []
        )
    return []


# ---------------------------------------------------------------------------
# Generic disk cache for provider_model_ids() — keeps /model picker fast.
# ---------------------------------------------------------------------------
#
# Without this layer, every picker open re-fetches a local endpoint's model
# listing and makes the UI feel sluggish.
#
# Cache strategy:
#   - One JSON file at $MARLOW_HOME/provider_models_cache.json
#   - Per-provider entries keyed by (provider, credential fingerprint)
#   - Credential fingerprint = sha256 of env-var values that the provider
#     normally reads. Swap your OPENAI_API_KEY and the entry invalidates.
#   - 1h TTL by default. `force_refresh=True` skips the cache entirely
#     and overwrites it on success.
#   - Only NON-EMPTY results are cached. An empty/None response from a
#     transient network error never gets pinned.
#   - Cache file is best-effort. Any read/write error degrades silently
#     to a live fetch — the picker keeps working.

_PROVIDER_MODELS_CACHE_TTL = 3600  # 1h


def _provider_models_cache_path() -> Path:
    from marlow_constants import get_marlow_home

    return get_marlow_home() / "provider_models_cache.json"


def _credential_fingerprint(provider: str) -> str:
    """Return a short hash representing the credentials that
    ``provider_model_ids(provider)`` would see right now.

    Rotating relevant API key/base URL variables invalidates the cached entry.
    Codex auth changes are detected through ``$MARLOW_HOME/auth.json``.
    """
    import hashlib
    import os as _os

    parts: list[str] = []

    # Env vars from PROVIDER_REGISTRY for this slug
    try:
        from marlow_cli.auth import PROVIDER_REGISTRY

        pcfg = PROVIDER_REGISTRY.get(provider)
        if pcfg is not None:
            for ev in getattr(pcfg, "api_key_env_vars", ()) or ():
                parts.append(f"{ev}={_os.environ.get(ev, '')}")
            bev = getattr(pcfg, "base_url_env_var", "") or ""
            if bev:
                parts.append(f"{bev}={_os.environ.get(bev, '')}")
    except Exception:
        pass

    # OAuth / external-file mtimes that change on re-auth
    try:
        from marlow_constants import get_marlow_home

        for rel in ("auth.json",):
            p = get_marlow_home() / rel
            try:
                parts.append(f"{rel}@{p.stat().st_mtime_ns}")
            except FileNotFoundError:
                parts.append(f"{rel}@missing")
            except Exception:
                pass
    except Exception:
        pass

    # Codex CLI credentials can be imported by the retained login flow.
    for path in (_os.path.expanduser("~/.codex/auth.json"),):
        try:
            mt = _os.stat(path).st_mtime_ns
            parts.append(f"{path}@{mt}")
        except FileNotFoundError:
            parts.append(f"{path}@missing")
        except Exception:
            pass

    blob = "|".join(parts).encode("utf-8", errors="replace")
    # blake2b for cache-key fingerprinting only — not for credential storage.
    # We never reverse this hash; collisions are harmless (worst case: cache
    # miss → live re-fetch). Use blake2b instead of sha256 here because
    # CodeQL's `py/weak-sensitive-data-hashing` rule flags sha256 over env
    # vars whose names contain "API_KEY" / "TOKEN" even when the hash is
    # used as an identity fingerprint, not for password storage. blake2b
    # is a keyed-hash primitive and isn't flagged.
    return hashlib.blake2b(blob, digest_size=8).hexdigest()


def _load_provider_models_cache() -> dict:
    """Return the full cache dict, or {} on any error."""
    try:
        path = _provider_models_cache_path()
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_provider_models_cache(data: dict) -> None:
    """Persist the cache dict. Best-effort — silent on any error."""
    try:
        from utils import atomic_json_write

        path = _provider_models_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(path, data, indent=None)
    except Exception:
        pass


def cached_provider_model_ids(
    provider: Optional[str],
    *,
    force_refresh: bool = False,
    ttl_seconds: int = _PROVIDER_MODELS_CACHE_TTL,
) -> list[str]:
    """Disk-cached wrapper around :func:`provider_model_ids`.

    Hits the cache when fresh; otherwise calls the live function and
    persists a non-empty result. Always returns a list (never None).
    """
    normalized = normalize_provider(provider) or (provider or "")
    if not normalized:
        return []

    cache = _load_provider_models_cache()
    fp = _credential_fingerprint(normalized)
    entry = cache.get(normalized)
    now = time.time()

    if (
        not force_refresh
        and isinstance(entry, dict)
        and entry.get("fp") == fp
        and isinstance(entry.get("models"), list)
        and entry["models"]
        and (now - float(entry.get("at", 0))) < ttl_seconds
    ):
        return list(entry["models"])

    # Cache miss / stale / forced refresh — call the live path.
    live = provider_model_ids(normalized, force_refresh=force_refresh)
    if live:
        cache[normalized] = {
            "fp": fp,
            "at": now,
            "models": list(live),
        }
        _save_provider_models_cache(cache)
        return list(live)

    # Live fetch returned nothing. If we have a stale entry with the
    # SAME fingerprint, prefer it over an empty result — stale data
    # beats no data when the network is flaky.
    if (
        isinstance(entry, dict)
        and entry.get("fp") == fp
        and isinstance(entry.get("models"), list)
        and entry["models"]
    ):
        return list(entry["models"])
    return list(live or [])


def clear_provider_models_cache(provider: Optional[str] = None) -> None:
    """Drop a single provider's cache entry, or wipe the whole cache.

    ``provider=None`` wipes everything; otherwise only that provider's
    entry is removed. Used by ``/model --refresh`` and
    ``marlow model --refresh``.
    """
    try:
        if provider is None:
            path = _provider_models_cache_path()
            if path.exists():
                path.unlink()
            return
        cache = _load_provider_models_cache()
        normalized = normalize_provider(provider) or provider or ""
        if normalized in cache:
            del cache[normalized]
            _save_provider_models_cache(cache)
    except Exception:
        pass


def _payload_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = payload.get("data", [])
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


def validate_requested_model(
    model_name: str,
    provider: Optional[str],
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    api_mode: Optional[str] = None,
) -> dict[str, Any]:
    """Validate model selection for retained Codex and compatible endpoints."""
    del api_mode
    requested = (model_name or "").strip()
    if not requested:
        return {
            "accepted": False,
            "persist": False,
            "recognized": False,
            "message": "Model name cannot be empty.",
        }
    if any(ch.isspace() for ch in requested):
        return {
            "accepted": False,
            "persist": False,
            "recognized": False,
            "message": "Model names cannot contain spaces.",
        }

    normalized = normalize_provider(provider)
    if normalized == "openai-codex":
        models = provider_model_ids(normalized)
        recognized = requested in models
        if not recognized:
            similar = get_close_matches(requested, models, n=3, cutoff=0.45)
            suffix = f" Similar models: {', '.join(similar)}." if similar else ""
            return {
                "accepted": True,
                "persist": True,
                "recognized": False,
                "message": (
                    f"`{requested}` is not in the current OpenAI Codex model listing; "
                    f"it will be tried as entered.{suffix}"
                ),
            }
        return {
            "accepted": True,
            "persist": True,
            "recognized": True,
            "message": "",
        }

    if normalized == "lmstudio":
        try:
            models = probe_lmstudio_models(api_key=api_key, base_url=base_url)
        except Exception as exc:
            return {
                "accepted": False,
                "persist": False,
                "recognized": False,
                "message": str(exc),
            }
        if models is None:
            return {
                "accepted": False,
                "persist": False,
                "recognized": False,
                "message": "Could not reach LM Studio to validate the model.",
            }
        recognized = requested in models
        return {
            "accepted": recognized,
            "persist": recognized,
            "recognized": recognized,
            "message": ""
            if recognized
            else f"Load `{requested}` in LM Studio and try again.",
        }

    if normalized in {"custom", "local", ""}:
        models = fetch_api_models(api_key or "", base_url or "") if base_url else []
        if models:
            recognized = requested in models
            return {
                "accepted": recognized,
                "persist": recognized,
                "recognized": recognized,
                "message": ""
                if recognized
                else f"`{requested}` was not returned by the endpoint's /models API.",
            }
        return {
            "accepted": True,
            "persist": True,
            "recognized": False,
            "message": "Endpoint model discovery was unavailable; the model name was saved as entered.",
        }

    return {
        "accepted": False,
        "persist": False,
        "recognized": False,
        "message": f"Unsupported provider: {normalized or provider}",
    }


def _lmstudio_server_root(base_url: Optional[str]) -> Optional[str]:
    """Strip ``/v1`` suffix from an LM Studio base URL to get the native API root.

    Returns ``None`` when the base URL is empty/invalid.
    """
    root = (base_url or "").strip().rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    return root or None


def _lmstudio_request_headers(api_key: Optional[str] = None) -> dict:
    """Build HTTP headers for LM Studio native API requests."""
    headers = {"User-Agent": _MARLOW_USER_AGENT}
    token = str(api_key or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _lmstudio_fetch_raw_models(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 5.0,
) -> Optional[list[dict]]:
    """Fetch the raw model list from LM Studio's ``/api/v1/models``.

    Returns the ``models`` list of dicts on success, ``None`` on network
    errors or malformed responses.  Raises ``AuthError`` on HTTP 401/403.
    """
    server_root = _lmstudio_server_root(base_url)
    if not server_root:
        return None

    headers = _lmstudio_request_headers(api_key)
    request = urllib.request.Request(server_root + "/api/v1/models", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            from marlow_cli.auth import AuthError

            raise AuthError(
                f"LM Studio rejected the request with HTTP {exc.code}.",
                provider="lmstudio",
                code="auth_rejected",
            ) from exc
        import logging

        logging.getLogger(__name__).debug(
            "LM Studio probe at %s failed with HTTP %s",
            server_root,
            exc.code,
        )
        return None
    except Exception as exc:
        import logging

        logging.getLogger(__name__).debug(
            "LM Studio probe at %s failed: %s",
            server_root,
            exc,
        )
        return None

    raw_models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(raw_models, list):
        import logging

        logging.getLogger(__name__).debug(
            "LM Studio probe at %s returned malformed payload (no `models` list)",
            server_root,
        )
        return None
    return raw_models


def probe_lmstudio_models(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 5.0,
) -> Optional[list[str]]:
    """Probe LM Studio's model listing.

    Returns chat-capable model keys on success, including the valid empty-list
    case when the server is reachable but has no non-embedding models.
    Returns ``None`` on network errors, malformed responses, or empty/invalid
    base URLs.

    Raises ``AuthError`` on HTTP 401/403 so callers can surface token issues
    separately from reachability problems.
    """
    raw_models = _lmstudio_fetch_raw_models(
        api_key=api_key, base_url=base_url, timeout=timeout
    )
    if raw_models is None:
        return None

    keys: list[str] = []
    for raw in raw_models:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("type") or "").strip().lower() == "embedding":
            continue
        key = str(raw.get("key") or raw.get("id") or "").strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def fetch_lmstudio_models(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 5.0,
) -> list[str]:
    """Fetch LM Studio chat-capable model keys from native ``/api/v1/models``.

    Returns a list of model keys (e.g. ``publisher/model-name``) with embedding
    models filtered out. Returns an empty list on network errors, malformed
    responses, or empty/invalid base URLs.

    Raises ``AuthError`` on HTTP 401/403 so callers can distinguish a missing
    or wrong ``LM_API_KEY`` from an unreachable server — the most common
    LM Studio support case once auth-enabled mode is turned on.
    """
    models = probe_lmstudio_models(api_key=api_key, base_url=base_url, timeout=timeout)
    return models or []


def ensure_lmstudio_model_loaded(
    model: str,
    base_url: Optional[str],
    api_key: Optional[str],
    target_context_length: int,
    timeout: float = 120.0,
) -> Optional[int]:
    """Ensure LM Studio has ``model`` loaded with at least ``target_context_length``.

    No-op when an instance is already loaded with sufficient context. Otherwise
    POSTs ``/api/v1/models/load`` to (re)load with the target context, capped
    at the model's ``max_context_length``. Returns the resolved loaded context
    length, or ``None`` when the probe / load failed.
    """
    server_root = _lmstudio_server_root(base_url)
    if not server_root:
        return None

    headers = _lmstudio_request_headers(api_key)

    try:
        raw_models = _lmstudio_fetch_raw_models(
            api_key=api_key, base_url=base_url, timeout=10
        )
    except Exception:
        raw_models = None
    if raw_models is None:
        return None

    target_entry = None
    for raw in raw_models:
        if not isinstance(raw, dict):
            continue
        if raw.get("key") == model or raw.get("id") == model:
            target_entry = raw
            break
    if target_entry is None:
        return None

    max_ctx = target_entry.get("max_context_length")
    if isinstance(max_ctx, int) and max_ctx > 0:
        target_context_length = min(target_context_length, max_ctx)

    for inst in target_entry.get("loaded_instances") or []:
        cfg = inst.get("config") if isinstance(inst, dict) else None
        loaded_ctx = cfg.get("context_length") if isinstance(cfg, dict) else None
        if isinstance(loaded_ctx, int) and loaded_ctx >= target_context_length:
            return loaded_ctx

    body = json.dumps({
        "model": model,
        "context_length": target_context_length,
    }).encode()
    load_headers = dict(headers)
    load_headers["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                server_root + "/api/v1/models/load",
                data=body,
                headers=load_headers,
                method="POST",
            ),
            timeout=timeout,
        ) as resp:
            resp.read()
    except Exception:
        return None
    return target_context_length


def lmstudio_model_reasoning_options(
    model: str,
    base_url: Optional[str],
    api_key: Optional[str] = None,
    timeout: float = 5.0,
) -> list[str]:
    """Return the reasoning ``allowed_options`` LM Studio publishes for ``model``.

    Pulls ``capabilities.reasoning.allowed_options`` from ``/api/v1/models``.
    Returns ``[]`` when the model is unknown, the endpoint is unreachable,
    or the model does not declare a reasoning capability.
    """
    try:
        raw_models = _lmstudio_fetch_raw_models(
            api_key=api_key, base_url=base_url, timeout=timeout
        )
    except Exception:
        raw_models = None
    if not raw_models:
        return []

    for raw in raw_models:
        if not isinstance(raw, dict):
            continue
        if raw.get("key") != model and raw.get("id") != model:
            continue
        caps = raw.get("capabilities")
        reasoning = caps.get("reasoning") if isinstance(caps, dict) else None
        opts = reasoning.get("allowed_options") if isinstance(reasoning, dict) else None
        if isinstance(opts, list):
            return [str(o).strip().lower() for o in opts if isinstance(o, str)]
        return []
    return []


def probe_api_models(
    api_key: Optional[str],
    base_url: Optional[str],
    timeout: float = 5.0,
    api_mode: Optional[str] = None,
) -> dict[str, Any]:
    """Probe an OpenAI-compatible ``/models`` endpoint."""
    del api_mode
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        return {
            "models": None,
            "probed_url": None,
            "resolved_base_url": "",
            "suggested_base_url": None,
            "used_fallback": False,
        }

    if normalized.endswith("/v1"):
        alternate_base = normalized[:-3].rstrip("/")
    else:
        alternate_base = normalized + "/v1"

    candidates: list[tuple[str, bool]] = [(normalized, False)]
    if alternate_base and alternate_base != normalized:
        candidates.append((alternate_base, True))

    tried: list[str] = []
    headers: dict[str, str] = {"User-Agent": _MARLOW_USER_AGENT}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    for candidate_base, is_fallback in candidates:
        url = candidate_base.rstrip("/") + "/models"
        tried.append(url)
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
                return {
                    "models": [m.get("id", "") for m in data.get("data", [])],
                    "probed_url": url,
                    "resolved_base_url": candidate_base.rstrip("/"),
                    "suggested_base_url": alternate_base
                    if alternate_base != candidate_base
                    else normalized,
                    "used_fallback": is_fallback,
                }
        except Exception:
            continue

    return {
        "models": None,
        "probed_url": tried[0] if tried else normalized.rstrip("/") + "/models",
        "resolved_base_url": normalized,
        "suggested_base_url": alternate_base if alternate_base != normalized else None,
        "used_fallback": False,
    }


def fetch_api_models(
    api_key: Optional[str],
    base_url: Optional[str],
    timeout: float = 5.0,
    api_mode: Optional[str] = None,
) -> Optional[list[str]]:
    """Fetch the list of available model IDs from the provider's ``/models`` endpoint.

    Returns a list of model ID strings, or ``None`` if the endpoint could not
    be reached (network error, timeout, auth failure, etc.).
    """
    return probe_api_models(api_key, base_url, timeout=timeout, api_mode=api_mode).get(
        "models"
    )
