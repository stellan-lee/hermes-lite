"""Resolve the small set of inference runtimes retained by Marlow Lite.

Marlow Lite supports Codex authentication/Responses and explicitly configured
OpenAI-compatible or Responses-compatible endpoints.
Provider credential pools and bundled first-party provider integrations are
intentionally not part of this resolver.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from marlow_cli.auth import (
    AuthError,
    DEFAULT_CODEX_BASE_URL,
    format_auth_error,
    resolve_codex_runtime_credentials,
)
from marlow_cli.config import load_config, load_custom_provider_entries
from marlow_cli.providers import normalize_provider
from utils import base_url_hostname

logger = logging.getLogger(__name__)

_VALID_API_MODES = {
    "chat_completions",
    "codex_responses",
    "codex_app_server",
}
_LOCAL_PROVIDERS = {"custom", "local", "lmstudio"}


def _normalize_custom_provider_name(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


def _parse_api_mode(raw: Any) -> Optional[str]:
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in _VALID_API_MODES:
            return normalized
    return None


def _detect_api_mode_for_url(base_url: str) -> Optional[str]:
    """Return no inferred mode; retained endpoints use OpenAI wire formats."""
    del base_url
    return None


def _auto_detect_local_model(base_url: str) -> str:
    """Return the sole model exposed by a local compatible server, if any."""
    if not base_url:
        return ""
    try:
        import requests

        url = base_url.rstrip("/")
        if not url.endswith("/v1"):
            url += "/v1"
        response = requests.get(url + "/models", timeout=5)
        if response.ok:
            models = response.json().get("data", [])
            if len(models) == 1:
                return str(models[0].get("id", "") or "")
    except Exception as exc:
        logger.debug("Auto-detect model from %s failed: %s", base_url, exc)
    return ""


def _get_model_config() -> Dict[str, Any]:
    model_cfg = load_config().get("model")
    if isinstance(model_cfg, str) and model_cfg.strip():
        return {"default": model_cfg.strip()}
    if not isinstance(model_cfg, dict):
        return {}
    cfg = dict(model_cfg)
    if not cfg.get("default") and cfg.get("model"):
        cfg["default"] = cfg["model"]
    if not cfg.get("default"):
        base_url = str(cfg.get("base_url") or "").strip()
        if base_url and base_url_hostname(base_url) in {"localhost", "127.0.0.1", "::1"}:
            detected = _auto_detect_local_model(base_url)
            if detected:
                cfg["default"] = detected
    return cfg


def _maybe_apply_codex_app_server_runtime(
    *, provider: str, api_mode: str, model_cfg: Optional[Dict[str, Any]]
) -> str:
    """Apply the explicit Codex app-server opt-in to Codex only."""
    if provider != "openai-codex" or not model_cfg:
        return api_mode
    runtime = str(model_cfg.get("openai_runtime") or "").strip().lower()
    return "codex_app_server" if runtime == "codex_app_server" else api_mode


def resolve_requested_provider(requested: Optional[str] = None) -> str:
    """Resolve provider selection from argument, config, then environment."""
    if requested and requested.strip():
        return requested.strip().lower()
    cfg_provider = _get_model_config().get("provider")
    if isinstance(cfg_provider, str) and cfg_provider.strip():
        return cfg_provider.strip().lower()
    env_provider = os.getenv("MARLOW_INFERENCE_PROVIDER", "").strip().lower()
    return env_provider or "auto"


def _provider_entries() -> list[Dict[str, Any]]:
    config = load_config()
    return [
        dict(entry)
        for entry in load_custom_provider_entries(config)
        if isinstance(entry, dict)
    ]


def _get_named_custom_provider(requested_provider: str) -> Optional[Dict[str, Any]]:
    requested = _normalize_custom_provider_name(requested_provider or "")
    if not requested or requested in {"auto", "custom", "lmstudio"}:
        return None
    explicit_custom = requested.startswith("custom:")
    lookup = requested.removeprefix("custom:")
    if not explicit_custom and normalize_provider(requested) in {"openai-codex", "lmstudio"}:
        return None

    for entry in _provider_entries():
        names = {
            _normalize_custom_provider_name(str(entry.get("name") or "")),
            _normalize_custom_provider_name(str(entry.get("provider_key") or "")),
        }
        names.discard("")
        if lookup not in names:
            continue
        base_url = str(entry.get("base_url") or "").strip()
        if not base_url:
            continue
        result: Dict[str, Any] = {
            "name": str(entry.get("name") or lookup),
            "base_url": base_url,
            "api_key": str(entry.get("api_key") or "").strip(),
            "key_env": str(entry.get("key_env") or "").strip(),
            "model": str(entry.get("model") or "").strip(),
        }
        api_mode = _parse_api_mode(entry.get("api_mode"))
        if api_mode:
            result["api_mode"] = api_mode
        if isinstance(entry.get("extra_body"), dict):
            result["extra_body"] = dict(entry["extra_body"])
        return result
    return None


def _endpoint_api_key(
    *, base_url: str, explicit_api_key: str = "", configured_api_key: str = "", key_env: str = ""
) -> str:
    candidates = [
        explicit_api_key.strip(),
        configured_api_key.strip(),
        os.getenv(key_env, "").strip() if key_env else "",
    ]
    return next((value for value in candidates if value), "no-key-required")


def _custom_provider_request_overrides(custom_provider: Dict[str, Any]) -> Dict[str, Any]:
    extra_body = custom_provider.get("extra_body")
    return {"extra_body": dict(extra_body)} if isinstance(extra_body, dict) and extra_body else {}


def _resolve_named_custom_runtime(
    *, requested_provider: str, explicit_api_key: Optional[str] = None,
    explicit_base_url: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    custom = _get_named_custom_provider(requested_provider)
    if custom is None and requested_provider in {"custom", "local"} and explicit_base_url:
        base_url = explicit_base_url.strip().rstrip("/")
        return {
            "provider": "custom",
            "api_mode": "chat_completions",
            "base_url": base_url,
            "api_key": _endpoint_api_key(
                base_url=base_url,
                explicit_api_key=str(explicit_api_key or ""),
            ),
            "source": "direct-alias",
            "requested_provider": requested_provider,
        }
    if custom is None:
        return None
    base_url = str(explicit_base_url or custom["base_url"]).strip().rstrip("/")
    result: Dict[str, Any] = {
        "provider": "custom",
        "api_mode": custom.get("api_mode") or _detect_api_mode_for_url(base_url) or "chat_completions",
        "base_url": base_url,
        "api_key": _endpoint_api_key(
            base_url=base_url,
            explicit_api_key=str(explicit_api_key or ""),
            configured_api_key=str(custom.get("api_key") or ""),
            key_env=str(custom.get("key_env") or ""),
        ),
        "source": f"custom_provider:{custom.get('name', requested_provider)}",
        "requested_provider": requested_provider,
    }
    if custom.get("model"):
        result["model"] = custom["model"]
    overrides = _custom_provider_request_overrides(custom)
    if overrides:
        result["request_overrides"] = overrides
    return result


def _resolve_custom_runtime(
    *, requested_provider: str, model_cfg: Dict[str, Any],
    explicit_api_key: Optional[str], explicit_base_url: Optional[str],
) -> Dict[str, Any]:
    configured_provider = str(model_cfg.get("provider") or "").strip().lower()
    configured_url = str(model_cfg.get("base_url") or "").strip()
    env_url = os.getenv("CUSTOM_BASE_URL", "").strip()
    if requested_provider == "lmstudio":
        base_url = (
            str(explicit_base_url or "").strip()
            or (configured_url if configured_provider == "lmstudio" else "")
            or os.getenv("LM_BASE_URL", "").strip()
            or "http://127.0.0.1:1234/v1"
        )
        api_key = (
            str(explicit_api_key or "").strip()
            or str(model_cfg.get("api_key") or "").strip()
            or os.getenv("LM_API_KEY", "").strip()
            or "dummy-lm-api-key"
        )
        return {
            "provider": "lmstudio", "api_mode": "chat_completions",
            "base_url": base_url.rstrip("/"), "api_key": api_key,
            "source": "config", "requested_provider": requested_provider,
        }

    base_url = str(explicit_base_url or "").strip() or env_url
    if not base_url and configured_url:
        if configured_provider in _LOCAL_PROVIDERS or base_url_hostname(configured_url) in {
            "localhost", "127.0.0.1", "::1",
        }:
            base_url = configured_url
    if not base_url:
        raise AuthError(
            "No compatible endpoint configured. Set model.base_url in config.yaml "
            "or select a saved custom provider."
        )
    api_mode = (
        _parse_api_mode(model_cfg.get("api_mode"))
        or _detect_api_mode_for_url(base_url)
        or "chat_completions"
    )
    return {
        "provider": "custom",
        "api_mode": api_mode,
        "base_url": base_url.rstrip("/"),
        "api_key": _endpoint_api_key(
            base_url=base_url,
            explicit_api_key=str(explicit_api_key or ""),
            configured_api_key=str(model_cfg.get("api_key") or ""),
            key_env=str(model_cfg.get("key_env") or ""),
        ),
        "source": "config",
        "requested_provider": requested_provider,
    }


def resolve_runtime_provider(
    *, requested: Optional[str] = None, explicit_api_key: Optional[str] = None,
    explicit_base_url: Optional[str] = None, target_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve Codex or a configured compatible endpoint for execution."""
    del target_model  # The retained transports do not infer protocol from model names.
    requested_provider = resolve_requested_provider(requested)
    model_cfg = _get_model_config()

    named = _resolve_named_custom_runtime(
        requested_provider=requested_provider,
        explicit_api_key=explicit_api_key,
        explicit_base_url=explicit_base_url,
    )
    if named:
        return named

    provider = normalize_provider(requested_provider)
    if provider == "auto":
        cfg_provider = normalize_provider(str(model_cfg.get("provider") or ""))
        if cfg_provider and cfg_provider != "auto":
            provider = cfg_provider
        elif explicit_base_url or model_cfg.get("base_url"):
            provider = "custom"
        else:
            provider = "openai-codex"

    if provider == "openai-codex":
        creds: Dict[str, Any] = {}
        if not explicit_api_key:
            creds = resolve_codex_runtime_credentials()
        base_url = str(
            explicit_base_url or creds.get("base_url") or DEFAULT_CODEX_BASE_URL
        ).strip().rstrip("/")
        api_mode = _maybe_apply_codex_app_server_runtime(
            provider=provider, api_mode="codex_responses", model_cfg=model_cfg
        )
        return {
            "provider": provider,
            "api_mode": api_mode,
            "base_url": base_url,
            "api_key": str(explicit_api_key or creds.get("api_key") or ""),
            "source": "explicit" if explicit_api_key or explicit_base_url else creds.get("source", "codex-auth"),
            "last_refresh": creds.get("last_refresh"),
            "requested_provider": requested_provider,
        }

    if provider in _LOCAL_PROVIDERS:
        return _resolve_custom_runtime(
            requested_provider=provider,
            model_cfg=model_cfg,
            explicit_api_key=explicit_api_key,
            explicit_base_url=explicit_base_url,
        )

    raise AuthError(
        f"Provider {requested_provider!r} is not included in Marlow Lite. "
        "Configure it as a compatible custom endpoint instead."
    )


def format_runtime_provider_error(error: Exception) -> str:
    return format_auth_error(error) if isinstance(error, AuthError) else str(error)
