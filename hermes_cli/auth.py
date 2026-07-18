"""Codex authentication and secure local auth-state persistence."""

from __future__ import annotations

import json
import logging
import os
import ssl
import stat
import sys
import base64
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from hermes_cli.config import get_hermes_home, get_config_path, read_raw_config
from hermes_constants import secure_parent_dir
from utils import atomic_replace, atomic_yaml_write


logger = logging.getLogger(__name__)

import fcntl

# =============================================================================
# Constants
# =============================================================================

AUTH_STORE_VERSION = 1
AUTH_LOCK_TIMEOUT_SECONDS = 15.0

DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120

# LM Studio's default no-auth mode still requires *some* non-empty bearer for
# the API-key code paths (auxiliary_client, runtime resolver) to treat the
# provider as configured. This sentinel is sent only to LM Studio, never to
# any remote service.
LMSTUDIO_NOAUTH_PLACEHOLDER = "dummy-lm-api-key"


# =============================================================================
# Provider Registry
# =============================================================================


@dataclass
class ProviderConfig:
    """Describes a known inference provider."""

    id: str
    name: str
    auth_type: str  # "oauth_external" or "api_key"
    inference_base_url: str = ""
    client_id: str = ""
    scope: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)
    # For API-key providers: env vars to check (in priority order)
    api_key_env_vars: tuple = ()
    # Optional env var for base URL override
    base_url_env_var: str = ""


PROVIDER_REGISTRY: Dict[str, ProviderConfig] = {
    "openai-codex": ProviderConfig(
        id="openai-codex",
        name="OpenAI Codex",
        auth_type="oauth_external",
        inference_base_url=DEFAULT_CODEX_BASE_URL,
    ),
    "lmstudio": ProviderConfig(
        id="lmstudio",
        name="LM Studio",
        auth_type="api_key",
        inference_base_url="http://127.0.0.1:1234/v1",
        api_key_env_vars=("LM_API_KEY",),
        base_url_env_var="LM_BASE_URL",
    ),
}


_PLACEHOLDER_SECRET_VALUES = {
    "*",
    "**",
    "***",
    "changeme",
    "your_api_key",
    "your_api_key_here",
    "your-api-key",
    "placeholder",
    "example",
    "dummy",
    "null",
    "none",
}


def has_usable_secret(value: Any, *, min_length: int = 4) -> bool:
    """Return True when a configured secret looks usable, not empty/placeholder."""
    if not isinstance(value, str):
        return False
    cleaned = value.strip()
    if len(cleaned) < min_length:
        return False
    if cleaned.lower() in _PLACEHOLDER_SECRET_VALUES:
        return False
    return True


# =============================================================================
# Error Types
# =============================================================================

# Error code marking upstream rate-limit / usage-quota exhaustion (HTTP 429).
# Such failures are transient and re-authenticating cannot resolve them, so
# they must be kept distinct from missing/expired-credential errors.
CODEX_RATE_LIMITED_CODE = "codex_rate_limited"


class AuthError(RuntimeError):
    """Structured auth error with UX mapping hints."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        code: Optional[str] = None,
        relogin_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.code = code
        self.relogin_required = relogin_required


def is_rate_limited_auth_error(error: Exception) -> bool:
    """True when an :class:`AuthError` represents upstream rate-limiting / quota
    exhaustion rather than missing or invalid credentials.

    These failures are transient — re-authenticating cannot resolve them — so
    callers should surface a "retry later" notice and prefer a fallback chain
    instead of prompting the operator to run ``hermes auth``.
    """
    return (
        isinstance(error, AuthError)
        and not error.relogin_required
        and error.code == CODEX_RATE_LIMITED_CODE
    )


def _parse_retry_after_seconds(headers: Any) -> Optional[int]:
    """Best-effort parse of a ``Retry-After`` header into whole seconds.

    Supports the delta-seconds form (e.g. ``"120"``). HTTP-date forms and
    missing/unparseable values return ``None`` rather than guessing.
    """
    if headers is None:
        return None
    try:
        raw = headers.get("retry-after")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        seconds = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def format_auth_error(error: Exception) -> str:
    """Map authentication failures to concise user-facing guidance."""
    if not isinstance(error, AuthError):
        return str(error)
    if error.relogin_required:
        return f"{error} Run `hermes model` to re-authenticate."
    return str(error)


# =============================================================================
# Auth Store — persistence layer for ~/.hermes/auth.json
# =============================================================================


def _auth_file_path() -> Path:
    path = get_hermes_home() / "auth.json"
    # Seat belt: if pytest is running and HERMES_HOME resolves to the real
    # user's auth store, refuse rather than silently corrupt it. This catches
    # tests that forgot to monkeypatch HERMES_HOME, tests invoked without the
    # hermetic conftest, or sandbox escapes via threads/subprocesses. In
    # production (no PYTEST_CURRENT_TEST) this is a single dict lookup.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        real_home_auth = (Path.home() / ".hermes" / "auth.json").resolve(strict=False)
        try:
            resolved = path.resolve(strict=False)
        except Exception:
            resolved = path
        if resolved == real_home_auth:
            raise RuntimeError(
                f"Refusing to touch real user auth store during test run: {path}. "
                "Set HERMES_HOME to a tmp_path in your test fixture, or run "
                "via scripts/run_tests.sh for hermetic CI-parity env."
            )
    return path


def _global_auth_file_path() -> Optional[Path]:
    """Return the global-root auth.json when the process is in profile mode.

    Returns ``None`` when the profile and global root resolve to the same
    directory (classic mode, or custom HERMES_HOME that is not a profile).
    Used by read-only fallback paths so providers authed at the root are
    visible to profile processes that haven't configured them locally.

    Profile-local provider state shadows this fallback.
    """
    try:
        from hermes_constants import get_default_hermes_root

        global_root = get_default_hermes_root()
    except Exception:
        return None
    profile_home = get_hermes_home()
    try:
        if profile_home.resolve(strict=False) == global_root.resolve(strict=False):
            return None
    except Exception:
        if profile_home == global_root:
            return None
    # No pytest seat belt here: this is a pure read-only path, and
    # ``_load_global_auth_store()`` wraps the read in a try/except so an
    # unreadable global file can never break the profile process.  The
    # write-side seat belt still lives on ``_auth_file_path()`` where it
    # belongs (that's what protects the real user's auth store from being
    # corrupted by a mis-configured test).
    return global_root / "auth.json"


def _load_global_auth_store() -> Dict[str, Any]:
    """Load the global-root auth store (read-only fallback).

    Returns an empty dict when no global fallback exists (classic mode,
    or the global auth.json is absent). Never raises on missing file.

    Seat belt: under pytest, refuses to read the real user's
    ``~/.hermes/auth.json`` even when HERMES_HOME is set to a profile
    path. The hermetic conftest does not redirect ``HOME``, so
    ``get_default_hermes_root()`` for a profile-shaped HERMES_HOME can
    still resolve to the real user's home on a dev machine. That would
    leak real credentials into tests. This guard uses the unmodified
    ``HOME`` env var (what ``os.path.expanduser('~')`` would resolve to),
    not ``Path.home()``, because ``Path.home`` is sometimes monkeypatched
    by fixtures that want to relocate the global root to a tmp path.
    """
    global_path = _global_auth_file_path()
    if global_path is None or not global_path.exists():
        return {}
    if os.environ.get("PYTEST_CURRENT_TEST"):
        real_home_env = os.environ.get("HOME", "")
        if real_home_env:
            real_root = Path(real_home_env) / ".hermes" / "auth.json"
            try:
                if global_path.resolve(strict=False) == real_root.resolve(strict=False):
                    return {}
            except Exception:
                pass
    try:
        return _load_auth_store(global_path)
    except Exception:
        # A malformed global store must not break profile reads. The
        # profile's own auth store is still authoritative.
        return {}


def _auth_lock_path() -> Path:
    return _auth_file_path().with_suffix(".lock")


_auth_lock_holder = threading.local()


@contextmanager
def _file_lock(
    lock_path: Path,
    holder: threading.local,
    timeout_seconds: float,
    timeout_message: str,
):
    """Cross-process advisory flock helper.

    Reentrant per-thread via ``holder.depth``.
    Callers supply their own ``threading.local`` so independent locks
    so independent stores don't share reentrancy
    state — that would let one lock's reentrant acquisition silently skip
    the other's kernel-level flock.
    """
    if getattr(holder, "depth", 0) > 0:
        holder.depth += 1
        try:
            yield
        finally:
            holder.depth -= 1
        return

    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        deadline = time.monotonic() + max(1.0, timeout_seconds)
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError, PermissionError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(timeout_message)
                time.sleep(0.05)

        holder.depth = 1
        try:
            yield
        finally:
            holder.depth = 0
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except (OSError, IOError):
                pass


@contextmanager
def _auth_store_lock(timeout_seconds: float = AUTH_LOCK_TIMEOUT_SECONDS):
    """Cross-process advisory lock for auth.json reads+writes.  Reentrant.

    Callers must keep this lock outermost when coordinating with another
    store lock; violating that order risks deadlock.
    against a concurrent import on the shared store.
    """
    with _file_lock(
        _auth_lock_path(),
        _auth_lock_holder,
        timeout_seconds,
        "Timed out waiting for auth store lock",
    ):
        yield


def _load_auth_store(auth_file: Optional[Path] = None) -> Dict[str, Any]:
    auth_file = auth_file or _auth_file_path()
    if not auth_file.exists():
        return {"version": AUTH_STORE_VERSION, "providers": {}}

    try:
        raw = json.loads(auth_file.read_text())
    except Exception as exc:
        corrupt_path = auth_file.with_suffix(".json.corrupt")
        try:
            import shutil

            shutil.copy2(auth_file, corrupt_path)
        except Exception:
            pass
        logger.warning(
            "auth: failed to parse %s (%s) — starting with empty store. "
            "Corrupt file preserved at %s",
            auth_file,
            exc,
            corrupt_path,
        )
        return {"version": AUTH_STORE_VERSION, "providers": {}}

    if isinstance(raw, dict) and isinstance(raw.get("providers"), dict):
        raw.setdefault("providers", {})
        return raw

    return {"version": AUTH_STORE_VERSION, "providers": {}}


def _save_auth_store(auth_store: Dict[str, Any]) -> Path:
    auth_file = _auth_file_path()
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    # Tighten parent dir to 0o700 so siblings can't traverse to creds.
    # secure_parent_dir refuses to chmod / or top-level dirs (#25821).
    secure_parent_dir(auth_file)
    auth_store["version"] = AUTH_STORE_VERSION
    auth_store["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(auth_store, indent=2) + "\n"
    tmp_path = auth_file.with_name(
        f"{auth_file.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    )
    try:
        # Create with 0o600 atomically via os.open(O_EXCL) + fdopen to close
        # the TOCTOU window where default umask (often 0o644) briefly exposed
        # OAuth tokens to other local users between open() and chmod().
        # Mirrors agent/google_oauth.py (#19673) and tools/mcp_oauth.py (#21148).
        fd = os.open(
            str(tmp_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        atomic_replace(tmp_path, auth_file)
        try:
            dir_fd = os.open(str(auth_file.parent), os.O_RDONLY)
        except OSError:
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
    # Restrict file permissions to owner only
    try:
        auth_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return auth_file


def _load_provider_state(
    auth_store: Dict[str, Any], provider_id: str
) -> Optional[Dict[str, Any]]:
    """Return a provider's persisted state.

    In profile mode, falls back to the global-root ``auth.json`` when the
    profile has no entry for ``provider_id``. This mirrors the per-provider
    shadowing used by the rest of the auth store: workers spawned in a profile
    can see a provider authenticated at global scope. Once the user logs in
    inside the profile, profile state shadows global state on the next read.
    """
    providers = auth_store.get("providers")
    if isinstance(providers, dict):
        state = providers.get(provider_id)
        if isinstance(state, dict):
            return dict(state)

    # Read-only fallback to the global-root auth store (profile mode only;
    # returns empty dict in classic mode so this is a no-op).
    global_store = _load_global_auth_store()
    if global_store:
        global_providers = global_store.get("providers")
        if isinstance(global_providers, dict):
            global_state = global_providers.get(provider_id)
            if isinstance(global_state, dict):
                return dict(global_state)
    return None


def _save_provider_state(
    auth_store: Dict[str, Any], provider_id: str, state: Dict[str, Any]
) -> None:
    providers = auth_store.setdefault("providers", {})
    if not isinstance(providers, dict):
        auth_store["providers"] = {}
        providers = auth_store["providers"]
    providers[provider_id] = state
    auth_store["active_provider"] = provider_id


def _store_provider_state(
    auth_store: Dict[str, Any],
    provider_id: str,
    state: Dict[str, Any],
    *,
    set_active: bool = True,
) -> None:
    providers = auth_store.setdefault("providers", {})
    if not isinstance(providers, dict):
        auth_store["providers"] = {}
        providers = auth_store["providers"]
    providers[provider_id] = state
    if set_active:
        auth_store["active_provider"] = provider_id


def is_known_auth_provider(provider_id: str) -> bool:
    return (provider_id or "").strip().lower() in PROVIDER_REGISTRY


def get_auth_provider_display_name(provider_id: str) -> str:
    normalized = (provider_id or "").strip().lower()
    config = PROVIDER_REGISTRY.get(normalized)
    return config.name if config else provider_id


def get_provider_auth_state(provider_id: str) -> Optional[Dict[str, Any]]:
    """Return profile auth state, falling back to the global profile root."""
    return _load_provider_state(_load_auth_store(), provider_id)


def get_active_provider() -> Optional[str]:
    return _load_auth_store().get("active_provider")


def is_provider_explicitly_configured(provider_id: str) -> bool:
    normalized = (provider_id or "").strip().lower()
    if get_active_provider() == normalized:
        return True
    try:
        from hermes_cli.config import load_config

        model = load_config().get("model")
        if (
            isinstance(model, dict)
            and str(model.get("provider") or "").strip().lower() == normalized
        ):
            return True
    except Exception:
        pass
    config = PROVIDER_REGISTRY.get(normalized)
    return bool(
        config
        and any(
            has_usable_secret(os.getenv(name, "")) for name in config.api_key_env_vars
        )
    )


def clear_provider_auth(provider_id: Optional[str] = None) -> bool:
    """Delete one provider's persisted credentials."""
    with _auth_store_lock():
        auth_store = _load_auth_store()
        target = provider_id or auth_store.get("active_provider")
        if not target:
            return False
        providers = auth_store.setdefault("providers", {})
        cleared = (
            isinstance(providers, dict) and providers.pop(target, None) is not None
        )
        if auth_store.get("active_provider") == target:
            auth_store["active_provider"] = None
            cleared = True
        if cleared:
            _save_auth_store(auth_store)
        return cleared


def deactivate_provider() -> None:
    """Stop preferring OAuth without deleting stored Codex credentials."""
    with _auth_store_lock():
        auth_store = _load_auth_store()
        auth_store["active_provider"] = None
        _save_auth_store(auth_store)


def resolve_provider(
    requested: Optional[str] = None,
    *,
    explicit_api_key: Optional[str] = None,
    explicit_base_url: Optional[str] = None,
) -> str:
    """Resolve Codex or an explicitly configured compatible endpoint."""
    normalized = (requested or "auto").strip().lower()
    aliases = {
        "codex": "openai-codex",
        "openai_codex": "openai-codex",
        "lm-studio": "lmstudio",
        "lm_studio": "lmstudio",
        "local": "custom",
        "ollama": "custom",
        "vllm": "custom",
        "llamacpp": "custom",
        "llama.cpp": "custom",
        "llama-cpp": "custom",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in {*PROVIDER_REGISTRY, "custom"}:
        return normalized
    if normalized != "auto":
        # Named custom providers are defined under model.providers in
        # config.yaml. Keep their identifiers intact for the runtime resolver.
        config = read_raw_config()
        model = config.get("model") if isinstance(config, dict) else None
        providers = model.get("providers") if isinstance(model, dict) else None
        if isinstance(providers, dict) and normalized in providers:
            return normalized
        raise AuthError(
            f"Unknown provider '{normalized}'. Run 'hermes model' to configure Codex or a compatible endpoint.",
            code="invalid_provider",
        )
    if explicit_api_key or explicit_base_url:
        return "custom"

    configured = _get_config_provider()
    if configured and configured != "auto":
        if configured in PROVIDER_REGISTRY or configured == "custom":
            return configured
        config = read_raw_config()
        model = config.get("model") if isinstance(config, dict) else None
        providers = model.get("providers") if isinstance(model, dict) else None
        if isinstance(providers, dict) and configured in providers:
            return configured

    active = get_active_provider()
    if active == "openai-codex" and get_codex_auth_status().get("logged_in"):
        return active
    if os.getenv("LM_BASE_URL", "").strip() or os.getenv("LM_API_KEY", "").strip():
        return "lmstudio"
    raise AuthError(
        "No inference provider configured. Run 'hermes model' to choose Codex or configure a compatible endpoint.",
        code="no_provider_configured",
    )


def _decode_jwt_claims(token: Any) -> Dict[str, Any]:
    if not isinstance(token, str) or token.count(".") != 2:
        return {}
    payload = token.split(".")[1]
    payload += "=" * ((4 - len(payload) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload.encode("utf-8"))
        claims = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    return claims if isinstance(claims, dict) else {}


def _codex_access_token_is_expiring(access_token: Any, skew_seconds: int) -> bool:
    claims = _decode_jwt_claims(access_token)
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return float(exp) <= (time.time() + max(0, int(skew_seconds)))


def _read_codex_tokens(*, _lock: bool = True) -> Dict[str, Any]:
    """Read Codex OAuth tokens from Hermes auth store (~/.hermes/auth.json).

    Returns dict with 'tokens' (access_token, refresh_token) and 'last_refresh'.
    Raises AuthError if no Codex tokens are stored.
    """
    if _lock:
        with _auth_store_lock():
            auth_store = _load_auth_store()
    else:
        auth_store = _load_auth_store()
    state = _load_provider_state(auth_store, "openai-codex")
    if not state:
        raise AuthError(
            "No Codex credentials stored. Run `hermes auth` to authenticate.",
            provider="openai-codex",
            code="codex_auth_missing",
            relogin_required=True,
        )
    tokens = state.get("tokens")
    if not isinstance(tokens, dict):
        raise AuthError(
            "Codex auth state is missing tokens. Run `hermes auth` to re-authenticate.",
            provider="openai-codex",
            code="codex_auth_invalid_shape",
            relogin_required=True,
        )
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise AuthError(
            "Codex auth is missing access_token. Run `hermes auth` to re-authenticate.",
            provider="openai-codex",
            code="codex_auth_missing_access_token",
            relogin_required=True,
        )
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise AuthError(
            "Codex auth is missing refresh_token. Run `hermes auth` to re-authenticate.",
            provider="openai-codex",
            code="codex_auth_missing_refresh_token",
            relogin_required=True,
        )
    return {
        "tokens": tokens,
        "last_refresh": state.get("last_refresh"),
    }


def _save_codex_tokens(
    tokens: Dict[str, str], last_refresh: str = None, label: str = None
) -> None:
    """Save Codex OAuth tokens to Hermes auth store (~/.hermes/auth.json)."""
    if last_refresh is None:
        last_refresh = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with _auth_store_lock():
        auth_store = _load_auth_store()
        state = _load_provider_state(auth_store, "openai-codex") or {}
        state["tokens"] = tokens
        state["last_refresh"] = last_refresh
        state["auth_mode"] = "chatgpt"
        if label and str(label).strip():
            state["label"] = str(label).strip()
        _save_provider_state(auth_store, "openai-codex", state)
        _save_auth_store(auth_store)


def refresh_codex_oauth_pure(
    access_token: str,
    refresh_token: str,
    *,
    timeout_seconds: float = 20.0,
) -> Dict[str, Any]:
    """Refresh Codex OAuth tokens without mutating Hermes auth state."""
    del (
        access_token
    )  # Access token is only used by callers to decide whether to refresh.
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise AuthError(
            "Codex auth is missing refresh_token. Run `hermes auth` to re-authenticate.",
            provider="openai-codex",
            code="codex_auth_missing_refresh_token",
            relogin_required=True,
        )

    timeout = httpx.Timeout(max(5.0, float(timeout_seconds)))
    with httpx.Client(
        timeout=timeout, headers={"Accept": "application/json"}
    ) as client:
        response = client.post(
            CODEX_OAUTH_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CODEX_OAUTH_CLIENT_ID,
            },
        )

    if response.status_code == 429:
        # Upstream rate-limit / usage-quota exhaustion on the token endpoint.
        # The stored refresh token is still valid here — re-authenticating
        # cannot lift a quota cap. Classify distinctly from auth failures so
        # callers surface a "retry later" notice instead of a misleading
        # "run hermes auth" prompt (see issue #32790).
        retry_after = _parse_retry_after_seconds(getattr(response, "headers", None))
        if retry_after is not None:
            message = (
                f"Codex provider quota exhausted (429); retry after {retry_after}s. "
                "Credentials are still valid."
            )
        else:
            message = (
                "Codex provider quota exhausted (429). Credentials are still valid; "
                "retry after the usage limit resets."
            )
        raise AuthError(
            message,
            provider="openai-codex",
            code=CODEX_RATE_LIMITED_CODE,
            relogin_required=False,
        )

    if response.status_code != 200:
        code = "codex_refresh_failed"
        message = f"Codex token refresh failed with status {response.status_code}."
        relogin_required = False
        try:
            err = response.json()
            if isinstance(err, dict):
                err_obj = err.get("error")
                # OpenAI shape: {"error": {"code": "...", "message": "...", "type": "..."}}
                if isinstance(err_obj, dict):
                    nested_code = err_obj.get("code") or err_obj.get("type")
                    if isinstance(nested_code, str) and nested_code.strip():
                        code = nested_code.strip()
                    nested_msg = err_obj.get("message")
                    if isinstance(nested_msg, str) and nested_msg.strip():
                        message = f"Codex token refresh failed: {nested_msg.strip()}"
                # OAuth spec shape: {"error": "code_str", "error_description": "..."}
                elif isinstance(err_obj, str) and err_obj.strip():
                    code = err_obj.strip()
                    err_desc = err.get("error_description") or err.get("message")
                    if isinstance(err_desc, str) and err_desc.strip():
                        message = f"Codex token refresh failed: {err_desc.strip()}"
        except Exception:
            pass
        if code in {"invalid_grant", "invalid_token", "invalid_request"}:
            relogin_required = True
        if code == "refresh_token_reused":
            message = (
                "Codex refresh token was already consumed by another client "
                "(e.g. Codex CLI or VS Code extension). "
                "Run `codex` in your terminal to generate fresh tokens, "
                "then run `hermes auth` to re-authenticate."
            )
            relogin_required = True
        # A 401/403 from the token endpoint always means the refresh token
        # is invalid/expired — force relogin even if the body error code
        # wasn't one of the known strings above.
        if response.status_code in {401, 403} and not relogin_required:
            relogin_required = True
        raise AuthError(
            message,
            provider="openai-codex",
            code=code,
            relogin_required=relogin_required,
        )

    try:
        refresh_payload = response.json()
    except Exception as exc:
        raise AuthError(
            "Codex token refresh returned invalid JSON.",
            provider="openai-codex",
            code="codex_refresh_invalid_json",
            relogin_required=True,
        ) from exc

    refreshed_access = refresh_payload.get("access_token")
    if not isinstance(refreshed_access, str) or not refreshed_access.strip():
        raise AuthError(
            "Codex token refresh response was missing access_token.",
            provider="openai-codex",
            code="codex_refresh_missing_access_token",
            relogin_required=True,
        )

    updated = {
        "access_token": refreshed_access.strip(),
        "refresh_token": refresh_token.strip(),
        "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    next_refresh = refresh_payload.get("refresh_token")
    if isinstance(next_refresh, str) and next_refresh.strip():
        updated["refresh_token"] = next_refresh.strip()
    return updated


def _refresh_codex_auth_tokens(
    tokens: Dict[str, str],
    timeout_seconds: float,
) -> Dict[str, str]:
    """Refresh Codex access token using the refresh token.

    Saves the new tokens to Hermes auth store automatically.
    """
    refreshed = refresh_codex_oauth_pure(
        str(tokens.get("access_token", "") or ""),
        str(tokens.get("refresh_token", "") or ""),
        timeout_seconds=timeout_seconds,
    )
    updated_tokens = dict(tokens)
    updated_tokens["access_token"] = refreshed["access_token"]
    updated_tokens["refresh_token"] = refreshed["refresh_token"]

    _save_codex_tokens(updated_tokens)
    return updated_tokens


def _import_codex_cli_tokens() -> Optional[Dict[str, str]]:
    """Try to read tokens from ~/.codex/auth.json (Codex CLI shared file).

    Returns tokens dict if valid and not expired, None otherwise.
    Does NOT write to the shared file.
    """
    codex_home = os.getenv("CODEX_HOME", "").strip()
    if not codex_home:
        codex_home = str(Path.home() / ".codex")
    auth_path = Path(codex_home).expanduser() / "auth.json"
    if not auth_path.is_file():
        return None
    try:
        payload = json.loads(auth_path.read_text())
        tokens = payload.get("tokens")
        if not isinstance(tokens, dict):
            return None
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        if not access_token or not refresh_token:
            return None
        # Reject expired tokens — importing stale tokens from ~/.codex/
        # that can't be refreshed leaves the user stuck with "Login successful!"
        # but no working credentials.
        if _codex_access_token_is_expiring(access_token, 0):
            logger.debug(
                "Codex CLI tokens at %s are expired — skipping import.",
                auth_path,
            )
            return None
        return dict(tokens)
    except Exception:
        return None


def resolve_codex_runtime_credentials(
    *,
    force_refresh: bool = False,
    refresh_if_expiring: bool = True,
    refresh_skew_seconds: int = CODEX_ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
) -> Dict[str, Any]:
    """Resolve runtime credentials from Hermes's Codex token store."""
    data = _read_codex_tokens()

    tokens = dict(data["tokens"])
    access_token = str(tokens.get("access_token", "") or "").strip()
    refresh_timeout_seconds = float(
        os.getenv("HERMES_CODEX_REFRESH_TIMEOUT_SECONDS", "20")
    )

    should_refresh = bool(force_refresh)
    if (not should_refresh) and refresh_if_expiring:
        should_refresh = _codex_access_token_is_expiring(
            access_token, refresh_skew_seconds
        )
    if should_refresh:
        # Re-read under lock to avoid racing with other Hermes processes
        with _auth_store_lock(
            timeout_seconds=max(
                float(AUTH_LOCK_TIMEOUT_SECONDS), refresh_timeout_seconds + 5.0
            )
        ):
            data = _read_codex_tokens(_lock=False)
            tokens = dict(data["tokens"])
            access_token = str(tokens.get("access_token", "") or "").strip()

            should_refresh = bool(force_refresh)
            if (not should_refresh) and refresh_if_expiring:
                should_refresh = _codex_access_token_is_expiring(
                    access_token, refresh_skew_seconds
                )

            if should_refresh:
                tokens = _refresh_codex_auth_tokens(tokens, refresh_timeout_seconds)
                access_token = str(tokens.get("access_token", "") or "").strip()

    base_url = (
        os.getenv("HERMES_CODEX_BASE_URL", "").strip().rstrip("/")
        or DEFAULT_CODEX_BASE_URL
    )

    return {
        "provider": "openai-codex",
        "base_url": base_url,
        "api_key": access_token,
        "source": "hermes-auth-store",
        "last_refresh": data.get("last_refresh"),
        "auth_mode": "chatgpt",
    }


def get_codex_auth_status() -> Dict[str, Any]:
    """Return the Codex OAuth status from the single auth-store entry."""
    try:
        creds = resolve_codex_runtime_credentials()
        return {
            "logged_in": True,
            "auth_store": str(_auth_file_path()),
            "last_refresh": creds.get("last_refresh"),
            "auth_mode": creds.get("auth_mode"),
            "source": creds.get("source"),
            "api_key": creds.get("api_key"),
        }
    except AuthError as exc:
        return {
            "logged_in": False,
            "auth_store": str(_auth_file_path()),
            "error": str(exc),
        }


def get_auth_status(provider_id: Optional[str] = None) -> Dict[str, Any]:
    """Return status for the retained built-in authentication providers."""
    target = (provider_id or get_active_provider() or "").strip().lower()
    if target == "openai-codex":
        return get_codex_auth_status()
    if target == "lmstudio":
        return {
            "provider": "lmstudio",
            "logged_in": True,
            "base_url": os.getenv("LM_BASE_URL", "").strip()
            or PROVIDER_REGISTRY["lmstudio"].inference_base_url,
        }
    return {"provider": target or None, "logged_in": False}


def _update_config_for_provider(
    provider_id: str,
    inference_base_url: str,
    default_model: Optional[str] = None,
) -> Path:
    """Update config.yaml and auth.json to reflect the active provider.

    When *default_model* is provided the function also writes it as the
    ``model.default`` value so gateway workers cannot observe a partially
    updated provider/model pair.
    """
    # Set active_provider in auth.json so auto-resolution picks this provider
    with _auth_store_lock():
        auth_store = _load_auth_store()
        auth_store["active_provider"] = provider_id
        _save_auth_store(auth_store)

    # Update config.yaml model section
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    config = read_raw_config()

    current_model = config.get("model")
    if isinstance(current_model, dict):
        model_cfg = dict(current_model)
    elif isinstance(current_model, str) and current_model.strip():
        model_cfg = {"default": current_model.strip()}
    else:
        model_cfg = {}

    model_cfg["provider"] = provider_id
    if inference_base_url and inference_base_url.strip():
        model_cfg["base_url"] = inference_base_url.rstrip("/")
    else:
        # Clear stale base_url to prevent contamination when switching providers
        model_cfg.pop("base_url", None)

    # Clear stale endpoint credentials and transport choices when switching
    # from a custom endpoint to a built-in retained provider.
    model_cfg.pop("api_key", None)
    model_cfg.pop("api_mode", None)

    # A provider switch may require replacing a namespaced model identifier.
    if default_model:
        cur_default = model_cfg.get("default", "")
        if not cur_default or "/" in cur_default:
            model_cfg["default"] = default_model

    config["model"] = model_cfg

    atomic_yaml_write(config_path, config, sort_keys=False)
    return config_path


def _get_config_provider() -> Optional[str]:
    """Return model.provider from config.yaml, normalized, if present."""
    try:
        config = read_raw_config()
    except Exception:
        return None
    if not config:
        return None
    model = config.get("model")
    if not isinstance(model, dict):
        return None
    provider = model.get("provider")
    if not isinstance(provider, str):
        return None
    provider = provider.strip().lower()
    return provider or None


def _config_provider_matches(provider_id: Optional[str]) -> bool:
    """Return True when config.yaml currently selects *provider_id*."""
    if not provider_id:
        return False
    return _get_config_provider() == provider_id.strip().lower()


def _should_reset_config_provider_on_logout(provider_id: Optional[str]) -> bool:
    """Return True when logout should reset the model provider config."""
    if not provider_id:
        return False
    normalized = provider_id.strip().lower()
    return normalized in PROVIDER_REGISTRY and _config_provider_matches(normalized)


def _logout_default_provider_from_config() -> Optional[str]:
    """Fallback logout target when auth.json has no active provider.

    `hermes logout` historically keyed off auth.json.active_provider only.
    That left users stuck when auth state had already been cleared but
    config.yaml still selected an OAuth provider such as openai-codex for the
    agent model: there was no active auth provider to target, so logout printed
    "No provider is currently logged in" and never reset model.provider.
    """
    provider = _get_config_provider()
    if provider == "openai-codex":
        return provider
    return None


def _reset_config_provider() -> Path:
    """Reset config.yaml provider back to auto after logout."""
    config_path = get_config_path()
    if not config_path.exists():
        return config_path

    config = read_raw_config()
    if not config:
        return config_path

    model = config.get("model")
    if isinstance(model, dict):
        model["provider"] = "auto"
        model.pop("base_url", None)
        model.pop("api_key", None)
        model.pop("api_mode", None)
    atomic_yaml_write(config_path, config, sort_keys=False)
    return config_path


def _prompt_model_selection(
    model_ids: List[str],
    current_model: str = "",
    pricing: Optional[Dict[str, Dict[str, str]]] = None,
) -> Optional[str]:
    """Interactive model selection. Puts current_model first with a marker. Returns chosen model ID or None.

    If *pricing* is provided (``{model_id: {prompt, completion}}``), a compact
    price indicator is shown next to each model in aligned columns.

    """
    from hermes_cli.models import _format_price_per_mtok

    # Reorder: current model first, then the rest (deduplicated)
    ordered = []
    if current_model and current_model in model_ids:
        ordered.append(current_model)
    for mid in model_ids:
        if mid not in ordered:
            ordered.append(mid)

    all_models = list(ordered)

    # Column-aligned labels when pricing is available
    has_pricing = bool(pricing and any(pricing.get(m) for m in all_models))
    name_col = max((len(m) for m in all_models), default=0) + 2 if has_pricing else 0

    # Pre-compute formatted prices and dynamic column widths
    _price_cache: dict[str, tuple[str, str, str]] = {}
    price_col = 3  # minimum width
    cache_col = 0  # only set if any model has cache pricing
    has_cache = False
    if has_pricing:
        for mid in all_models:
            p = pricing.get(mid)  # type: ignore[union-attr]
            if p:
                inp = _format_price_per_mtok(p.get("prompt", ""))
                out = _format_price_per_mtok(p.get("completion", ""))
                cache_read = p.get("input_cache_read", "")
                cache = _format_price_per_mtok(cache_read) if cache_read else ""
                if cache:
                    has_cache = True
            else:
                inp, out, cache = "", "", ""
            _price_cache[mid] = (inp, out, cache)
            price_col = max(price_col, len(inp), len(out))
            cache_col = max(cache_col, len(cache))
        if has_cache:
            cache_col = max(cache_col, 5)  # minimum: "Cache" header

    def _label(mid):
        if has_pricing:
            inp, out, cache = _price_cache.get(mid, ("", "", ""))
            price_part = f" {inp:>{price_col}}  {out:>{price_col}}"
            if has_cache:
                price_part += f"  {cache:>{cache_col}}"
            base = f"{mid:<{name_col}}{price_part}"
        else:
            base = mid
        if mid == current_model:
            base += "  ← currently in use"
        return base

    # Default cursor on the current model (index 0 if it was reordered to top)
    default_idx = 0

    # Build a pricing header hint for the menu title
    menu_title = "Select default model:"
    if has_pricing:
        # Align the header with the model column.
        # Each choice is "  {label}" (2 spaces) and simple_term_menu prepends
        # a 3-char cursor region ("-> " or "   "), so content starts at col 5.
        pad = " " * 5
        header = f"\n{pad}{'':>{name_col}} {'In':>{price_col}}  {'Out':>{price_col}}"
        if has_cache:
            header += f"  {'Cache':>{cache_col}}"
        menu_title += header + "  /Mtok"

    # Try arrow-key menu first, fall back to number input.
    # Uses the shared curses radiolist (ESC/arrow-key handling that works
    # across terminals, incl. those that emit raw escape sequences) instead
    # of simple_term_menu, which conflicts with /dev/tty and left ESC/arrow
    # keys unreliable in the setup model picker.
    try:
        from hermes_cli.curses_ui import curses_radiolist

        choices = [_label(mid) for mid in ordered]
        choices.append("Enter custom model name")
        choices.append("Skip (keep current)")

        # The pricing column header is shown
        # as a multi-line description above the list so it survives the curses
        # screen clear. menu_title already embeds the aligned price header.
        desc_lines: list[str] = []
        if has_pricing:
            # menu_title is "Select default model:\n<pad><header>  /Mtok"
            # Keep only the header portion for the description.
            header_part = menu_title.split("\n", 1)
            if len(header_part) > 1:
                desc_lines.extend(header_part[1].splitlines())
        description = "\n".join(desc_lines) if desc_lines else None

        idx = curses_radiolist(
            "Select default model:",
            choices,
            selected=default_idx,
            cancel_returns=-1,
            description=description,
            searchable=True,
        )
        if idx < 0:
            return None
        print()
        if idx < len(ordered):
            return ordered[idx]
        elif idx == len(ordered):
            try:
                custom = input("Enter model name: ").strip()
            except (EOFError, KeyboardInterrupt):
                return None
            return custom if custom else None
        return None
    except (ImportError, NotImplementedError, OSError, subprocess.SubprocessError):
        pass

    # Fallback: numbered list
    print(menu_title)
    num_width = len(str(len(ordered) + 2))
    for i, mid in enumerate(ordered, 1):
        print(f"  {i:>{num_width}}. {_label(mid)}")
    n = len(ordered)
    print(f"  {n + 1:>{num_width}}. Enter custom model name")
    print(f"  {n + 2:>{num_width}}. Skip (keep current)")

    print()

    while True:
        try:
            choice = input(f"Choice [1-{n + 2}] (default: skip): ").strip()
            if not choice:
                return None
            idx = int(choice)
            if 1 <= idx <= n:
                return ordered[idx - 1]
            elif idx == n + 1:
                custom = input("Enter model name: ").strip()
                return custom if custom else None
            elif idx == n + 2:
                return None
            print(f"Please enter 1-{n + 2}")
        except ValueError:
            print("Please enter a number")
        except (KeyboardInterrupt, EOFError):
            return None


def _save_model_choice(model_id: str) -> None:
    """Save the selected model to config.yaml (single source of truth).

    The model is stored in config.yaml only — NOT in .env.  This avoids
    conflicts in multi-agent setups where env vars would stomp each other.
    """
    from hermes_cli.config import save_config, load_config

    config = load_config()
    # Always use dict format so provider/base_url can be stored alongside
    if isinstance(config.get("model"), dict):
        config["model"]["default"] = model_id
    else:
        config["model"] = {"default": model_id}
    save_config(config)


def login_command(args) -> None:
    """Deprecated: use 'hermes model' or 'hermes setup' instead."""
    print("The 'hermes login' command has been removed.")
    print("Use 'hermes auth' to manage credentials,")
    print("'hermes model' to select a provider, or 'hermes setup' for full setup.")
    raise SystemExit(0)


def _login_openai_codex(
    args,
    pconfig: ProviderConfig,
    *,
    force_new_login: bool = False,
) -> None:
    """OpenAI Codex login via device code flow. Tokens stored in ~/.hermes/auth.json."""

    del args, pconfig  # kept for parity with other provider login helpers

    # Check for existing Hermes-owned credentials
    if not force_new_login:
        try:
            existing = resolve_codex_runtime_credentials()
            # Verify the resolved token is actually usable (not expired).
            # resolve_codex_runtime_credentials attempts refresh, so if we get
            # here the token should be valid — but double-check before telling
            # the user "Login successful!".
            _resolved_key = existing.get("api_key", "")
            if (
                isinstance(_resolved_key, str)
                and _resolved_key
                and not _codex_access_token_is_expiring(_resolved_key, 60)
            ):
                print("Existing Codex credentials found in Hermes auth store.")
                try:
                    reuse = input("Use existing credentials? [Y/n]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    reuse = "y"
                if reuse in {"", "y", "yes"}:
                    config_path = _update_config_for_provider(
                        "openai-codex", existing.get("base_url", DEFAULT_CODEX_BASE_URL)
                    )
                    print()
                    print("Login successful!")
                    print(
                        f"  Config updated: {config_path} (model.provider=openai-codex)"
                    )
                    return
            else:
                print("Existing Codex credentials are expired. Starting fresh login...")
        except AuthError:
            pass

    # Check for existing Codex CLI tokens we can import
    if not force_new_login:
        cli_tokens = _import_codex_cli_tokens()
        if cli_tokens:
            print("Found existing Codex CLI credentials at ~/.codex/auth.json")
            print(
                "Hermes will create its own session to avoid conflicts with Codex CLI / VS Code."
            )
            try:
                do_import = (
                    input(
                        "Import these credentials? (a separate login is recommended) [y/N]: "
                    )
                    .strip()
                    .lower()
                )
            except (EOFError, KeyboardInterrupt):
                do_import = "n"
            if do_import in {"y", "yes"}:
                _save_codex_tokens(cli_tokens)
                base_url = (
                    os.getenv("HERMES_CODEX_BASE_URL", "").strip().rstrip("/")
                    or DEFAULT_CODEX_BASE_URL
                )
                config_path = _update_config_for_provider("openai-codex", base_url)
                print()
                print("Credentials imported. Note: if Codex CLI refreshes its token,")
                print("Hermes will keep working independently with its own session.")
                print(f"  Config updated: {config_path} (model.provider=openai-codex)")
                return

    # Run a fresh device code flow — Hermes gets its own OAuth session
    print()
    print("Signing in to OpenAI Codex...")
    print("(Hermes creates its own session — won't affect Codex CLI or VS Code)")
    print()

    creds = _codex_device_code_login()

    # Save tokens to Hermes auth store
    _save_codex_tokens(creds["tokens"], creds.get("last_refresh"))
    config_path = _update_config_for_provider(
        "openai-codex", creds.get("base_url", DEFAULT_CODEX_BASE_URL)
    )
    print()
    print("Login successful!")
    from hermes_constants import display_hermes_home as _dhh

    print(f"  Auth state: {_dhh()}/auth.json")
    print(f"  Config updated: {config_path} (model.provider=openai-codex)")


def _codex_device_code_login() -> Dict[str, Any]:
    """Run the OpenAI device code login flow and return credentials dict."""
    import time as _time

    issuer = "https://auth.openai.com"
    client_id = CODEX_OAUTH_CLIENT_ID

    # Step 1: Request device code
    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            resp = client.post(
                f"{issuer}/api/accounts/deviceauth/usercode",
                json={"client_id": client_id},
                headers={"Content-Type": "application/json"},
            )
    except Exception as exc:
        raise AuthError(
            f"Failed to request device code: {exc}",
            provider="openai-codex",
            code="device_code_request_failed",
        )

    if resp.status_code != 200:
        raise AuthError(
            f"Device code request returned status {resp.status_code}.",
            provider="openai-codex",
            code="device_code_request_error",
        )

    device_data = resp.json()
    user_code = device_data.get("user_code", "")
    device_auth_id = device_data.get("device_auth_id", "")
    poll_interval = max(3, int(device_data.get("interval", "5")))

    if not user_code or not device_auth_id:
        raise AuthError(
            "Device code response missing required fields.",
            provider="openai-codex",
            code="device_code_incomplete",
        )

    # Step 2: Show user the code
    print("To continue, follow these steps:\n")
    print("  1. Open this URL in your browser:")
    print(f"     \033[94m{issuer}/codex/device\033[0m\n")
    print("  2. Enter this code:")
    print(f"     \033[94m{user_code}\033[0m\n")
    print("Waiting for sign-in... (press Ctrl+C to cancel)")

    # Step 3: Poll for authorization code
    max_wait = 15 * 60  # 15 minutes
    start = _time.monotonic()
    code_resp = None

    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            while _time.monotonic() - start < max_wait:
                _time.sleep(poll_interval)
                poll_resp = client.post(
                    f"{issuer}/api/accounts/deviceauth/token",
                    json={"device_auth_id": device_auth_id, "user_code": user_code},
                    headers={"Content-Type": "application/json"},
                )

                if poll_resp.status_code == 200:
                    code_resp = poll_resp.json()
                    break
                elif poll_resp.status_code in {403, 404}:
                    continue  # User hasn't completed login yet
                else:
                    raise AuthError(
                        f"Device auth polling returned status {poll_resp.status_code}.",
                        provider="openai-codex",
                        code="device_code_poll_error",
                    )
    except KeyboardInterrupt:
        print("\nLogin cancelled.")
        raise SystemExit(130)

    if code_resp is None:
        raise AuthError(
            "Login timed out after 15 minutes.",
            provider="openai-codex",
            code="device_code_timeout",
        )

    # Step 4: Exchange authorization code for tokens
    authorization_code = code_resp.get("authorization_code", "")
    code_verifier = code_resp.get("code_verifier", "")
    redirect_uri = f"{issuer}/deviceauth/callback"

    if not authorization_code or not code_verifier:
        raise AuthError(
            "Device auth response missing authorization_code or code_verifier.",
            provider="openai-codex",
            code="device_code_incomplete_exchange",
        )

    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            token_resp = client.post(
                CODEX_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except Exception as exc:
        raise AuthError(
            f"Token exchange failed: {exc}",
            provider="openai-codex",
            code="token_exchange_failed",
        )

    if token_resp.status_code != 200:
        raise AuthError(
            f"Token exchange returned status {token_resp.status_code}.",
            provider="openai-codex",
            code="token_exchange_error",
        )

    tokens = token_resp.json()
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")

    if not access_token:
        raise AuthError(
            "Token exchange did not return an access_token.",
            provider="openai-codex",
            code="token_exchange_no_access_token",
        )

    # Return tokens for the caller to persist (no longer writes to ~/.codex/)
    base_url = (
        os.getenv("HERMES_CODEX_BASE_URL", "").strip().rstrip("/")
        or DEFAULT_CODEX_BASE_URL
    )

    return {
        "tokens": {
            "access_token": access_token,
            "refresh_token": refresh_token,
        },
        "base_url": base_url,
        "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "auth_mode": "chatgpt",
        "source": "device-code",
    }


def logout_command(args) -> None:
    """Clear auth state for a provider."""
    provider_id = getattr(args, "provider", None)

    if provider_id and not is_known_auth_provider(provider_id):
        print(f"Unknown provider: {provider_id}")
        raise SystemExit(1)

    active = get_active_provider()
    target = provider_id or active or _logout_default_provider_from_config()

    if not target:
        print("No provider is currently logged in.")
        return

    should_reset_config = _should_reset_config_provider_on_logout(target)
    provider_name = get_auth_provider_display_name(target)

    if clear_provider_auth(target) or should_reset_config:
        if should_reset_config:
            _reset_config_provider()
        print(f"Logged out of {provider_name}.")
        if should_reset_config:
            print("Run `hermes model` or configure an API key to use Hermes.")
        else:
            print("Model provider configuration was unchanged.")
    else:
        print(f"No auth state found for {provider_name}.")
