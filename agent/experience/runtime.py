"""Runtime boundary helpers for the Work Experience validation MVP.

Experience is intentionally available to one narrow producer in the first
release: a foreground turn from the classic local CLI. Every other caller is
named explicitly and fails closed. Keeping this as an enum instead of
inferring eligibility from ``agent.platform`` matters because both background
CLI tasks and the TUI currently identify themselves as ``"cli"``.

The request-copy helper in this module is the only supported way to attach an
experience block to model input. It always returns fresh message dictionaries
and fresh multimodal content parts, leaving canonical/persisted messages
untouched.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import math
import re
import uuid
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


logger = logging.getLogger(__name__)

_EXPERIENCE_TARGET_KEY = "_hermes_work_experience_target"


class TurnOrigin(StrEnum):
    """Immutable identity for the frontend/runtime that started a turn."""

    CLASSIC_CLI = "classic_cli"
    CLI_BACKGROUND = "cli_background"
    TUI = "tui"
    GATEWAY = "gateway"
    SUBAGENT = "subagent"
    BATCH = "batch"
    CRON = "cron"
    UNKNOWN = "unknown"

    @property
    def experience_eligible(self) -> bool:
        """Whether the MVP may read experience for this origin."""

        return self is TurnOrigin.CLASSIC_CLI


class ExperienceMode(StrEnum):
    """Global feature mode; project policy still has to grant access."""

    OFF = "off"
    CAPTURE = "capture"
    SHADOW = "shadow"
    ASSIST = "assist"

    @property
    def recall_enabled(self) -> bool:
        return self in {ExperienceMode.SHADOW, ExperienceMode.ASSIST}


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    """Non-secret provider identity used only for egress authorization."""

    trust_domain: str
    is_local: bool


@dataclass(frozen=True, slots=True)
class ExperienceRuntimeTurn:
    """One cached retrieval whose disclosure is checked on every request."""

    mode: ExperienceMode
    policy: Any
    service: Any
    result: Any
    max_primary_lessons: int = 2

    def context_for_request(
        self,
        *,
        provider: str | None,
        base_url: str | None,
    ) -> str:
        """Return provider-authorized context, or an empty fail-closed result."""

        if self.mode is not ExperienceMode.ASSIST:
            return ""
        if not bool(getattr(self.policy, "recall_allowed", False)) or not bool(
            getattr(self.policy, "injection_allowed", False)
        ):
            return ""
        identity = provider_identity(provider=provider, base_url=base_url)
        disclosures = tuple(getattr(self.result, "disclosures", ()) or ())
        if identity is None or not disclosures:
            return ""

        from agent.experience.safety import is_egress_allowed

        allowed: set[tuple[str, int]] = set()
        for disclosure in disclosures:
            if is_egress_allowed(
                sensitivity=disclosure.sensitivity,
                egress_policy=disclosure.egress_policy,
                producer_trust_domain=disclosure.producer_trust_domain,
                current_trust_domain=identity.trust_domain,
                current_provider_is_local=identity.is_local,
                max_egress_policy=self.policy.max_egress_policy,
            ):
                allowed.add((disclosure.item_id, disclosure.item_revision))

        selected = tuple(
            item
            for item in self.result.items
            if (item.item_id, item.item_revision) in allowed
        )[: self.max_primary_lessons]
        if not selected:
            return ""
        selected_result = replace(self.result, items=selected)
        # The concrete service performs a fresh DB-backed authorization check
        # using the identity of this exact request. Lightweight test/dry-run
        # formatters retain the small one-argument protocol.
        from agent.experience.service import ExperienceService

        if isinstance(self.service, ExperienceService):
            return self.service.format_context(
                selected_result,
                provider_trust_domain=identity.trust_domain,
                provider_is_local=identity.is_local,
            )
        return self.service.format_context(selected_result)


def normalize_turn_origin(value: TurnOrigin | str | None) -> TurnOrigin:
    """Return a known origin, treating malformed values as unsupported."""

    if isinstance(value, TurnOrigin):
        return value
    try:
        return TurnOrigin(str(value or "").strip().lower())
    except ValueError:
        return TurnOrigin.UNKNOWN


def normalize_experience_mode(value: ExperienceMode | str | None) -> ExperienceMode:
    """Return a known mode, defaulting malformed configuration to ``off``."""

    if isinstance(value, ExperienceMode):
        return value
    try:
        return ExperienceMode(str(value or "").strip().lower())
    except ValueError:
        return ExperienceMode.OFF


def provider_identity(
    *,
    provider: str | None,
    base_url: str | None,
) -> ProviderIdentity | None:
    """Derive a bounded trust domain without retaining credentials or paths."""

    raw_url = str(base_url or "").strip()
    provider_name = re.sub(
        r"[^a-z0-9._-]+",
        "-",
        str(provider or "").strip().casefold(),
    ).strip("-._")

    host = ""
    endpoint_id = ""
    if raw_url:
        try:
            candidate = raw_url if "://" in raw_url else f"https://{raw_url}"
            parsed = urlsplit(candidate)
            scheme = parsed.scheme.casefold()
            host = (parsed.hostname or "").casefold().rstrip(".")
            port = parsed.port
            if port is None:
                port = {"http": 80, "https": 443}.get(scheme, 0)
            if host and scheme:
                endpoint_id = hashlib.sha256(
                    f"{scheme}\0{host}\0{port}".encode("utf-8")
                ).hexdigest()[:24]
        except Exception:
            host = ""
            endpoint_id = ""

    # Work Experience locality is a privacy boundary, so it is deliberately
    # stricter than model-routing locality (which also treats RFC-1918 and
    # Tailscale peers as local for timeout tuning). Only this machine's
    # loopback interface qualifies for local-only experience.
    is_local = host == "localhost"
    if host and not is_local:
        try:
            is_local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_local = False

    if is_local:
        return ProviderIdentity("local-runtime", True)
    if provider_name:
        # Include the actual endpoint whenever one exists. A provider label is
        # configuration, not proof that two custom gateways share a disclosure
        # boundary. Native SDK providers with no URL fall back to their name.
        suffix = f"/{endpoint_id}" if endpoint_id else ""
        return ProviderIdentity(f"provider:{provider_name}{suffix}"[:128], False)
    if endpoint_id:
        return ProviderIdentity(f"endpoint:{endpoint_id}", False)
    return None


def prepare_experience_turn(
    agent: Any,
    *,
    raw_user_message: str | None,
    turn_origin: TurnOrigin | str | None,
) -> ExperienceRuntimeTurn | None:
    """Retrieve once for an eligible turn, failing open for normal work.

    Origin, runtime, raw-input, and global-mode checks intentionally happen
    before importing or constructing ``ExperienceStore``. Unsupported
    frontends and Codex app-server turns therefore perform zero experience
    database reads.
    """

    origin = normalize_turn_origin(turn_origin)
    if not origin.experience_eligible:
        return None
    if getattr(agent, "api_mode", None) == "codex_app_server":
        return None
    if not isinstance(raw_user_message, str) or not raw_user_message.strip():
        return None

    try:
        from hermes_cli.config import load_config

        raw_config = load_config().get("experience", {})
        if not isinstance(raw_config, Mapping):
            return None
        global_mode = normalize_experience_mode(raw_config.get("mode", "off"))
        if not global_mode.recall_enabled:
            return None

        identity = provider_identity(
            provider=getattr(agent, "provider", None),
            base_url=getattr(agent, "base_url", None),
        )
        if identity is None:
            return None

        from agent.experience.models import RetrievalQuery
        from agent.experience.safety import sanitize_for_storage
        from agent.experience.scope import ScopeResolver
        from agent.experience.service import ExperienceService
        from agent.experience.store import (
            ExperienceSchemaNotCurrentError,
            ExperienceStore,
        )
        from agent.runtime_cwd import resolve_agent_cwd
        from hermes_constants import get_hermes_home

        home = Path(get_hermes_home()).expanduser().resolve()
        safe_query = sanitize_for_storage(
            raw_user_message,
            field_name="raw_user_message",
            max_chars=4_000,
        )
        max_items = _bounded_int(
            raw_config.get("max_retrieved_items"), default=3, minimum=1, maximum=12
        )
        max_context = _bounded_int(
            raw_config.get("max_injected_chars"), default=1_500, minimum=256, maximum=1_500
        )
        min_confidence = _bounded_float(
            raw_config.get("min_retrieval_confidence"),
            default=0.55,
            minimum=0.0,
            maximum=1.0,
        )

        state_db_path = home / "state.db"
        try:
            store = ExperienceStore.open_current(state_db_path)
        except ExperienceSchemaNotCurrentError:
            store = ExperienceStore(state_db_path)
        with store:
            service = ExperienceService(
                store,
                scope_resolver=ScopeResolver(str(home)),
                max_retrieved_items=max_items,
                max_context_chars=max_context,
                min_confidence=min_confidence,
            )
            resolved = service.resolve_scope(str(resolve_agent_cwd()))
            effective_mode = _effective_mode(global_mode, resolved.policy)
            if effective_mode is None:
                return None
            query = RetrievalQuery(
                scope=resolved.as_ref(),
                query_text=safe_query,
                provider_trust_domain=identity.trust_domain,
                provider_is_local=identity.is_local,
                limit=max_items,
            )
            turn_id = f"turn_{uuid.uuid4().hex}"
            work_id = f"attempt_{uuid.uuid4().hex}"
            result = service.retrieve(
                query,
                turn_id=turn_id,
                work_id=work_id,
                require_injection_allowed=effective_mode is ExperienceMode.ASSIST,
            )

        # Ranking is frozen for retry stability. Formatting and declarations
        # reopen this explicit DB path briefly to recheck current governance.
        return ExperienceRuntimeTurn(
            mode=effective_mode,
            policy=resolved.policy,
            service=service,
            result=result,
        )
    except Exception as exc:
        # Metadata only: never log raw input, paths, provider URLs, or stored
        # lesson text. Experience failure must not fail the user's task.
        logger.info(
            "Work Experience recall skipped safely: error_type=%s",
            type(exc).__name__,
        )
        return None


def _effective_mode(
    global_mode: ExperienceMode,
    policy: Any,
) -> ExperienceMode | None:
    if global_mode not in {ExperienceMode.SHADOW, ExperienceMode.ASSIST}:
        return None
    if not bool(getattr(policy, "recall_allowed", False)):
        return None
    if global_mode is ExperienceMode.ASSIST and bool(
        getattr(policy, "injection_allowed", False)
    ):
        return ExperienceMode.ASSIST
    return ExperienceMode.SHADOW


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _bounded_float(
    value: Any,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(minimum, min(parsed, maximum))


def _copy_content(content: Any) -> Any:
    if not isinstance(content, list):
        return content
    return [dict(part) if isinstance(part, Mapping) else part for part in content]


def _append_context(content: Any, context: str) -> Any:
    """Append context to string or OpenAI-style multimodal user content."""

    if isinstance(content, str):
        separator = "\n\n" if content else ""
        return f"{content}{separator}{context}"
    if isinstance(content, list):
        parts = _copy_content(content)
        parts.append({"type": "text", "text": context})
        return parts
    # Unknown content shapes are never rewritten. Failing closed here avoids
    # accidentally serializing private attachment objects into a text prompt.
    return content


def copy_messages_with_experience_context(
    messages: Sequence[Mapping[str, Any]],
    *,
    current_user_index: int | None,
    context: str | None,
) -> list[dict[str, Any]]:
    """Return a wire-only copy with context on the current user message.

    A missing/stale index, non-user target, empty context, or unsupported
    content shape yields an ordinary copy with no experience attached. This
    makes retries and provider fallbacks safe to call unconditionally.
    """

    copied: list[dict[str, Any]] = []
    for message in messages:
        item = dict(message)
        if "content" in item:
            item["content"] = _copy_content(item.get("content"))
        copied.append(item)

    if not isinstance(context, str) or not context.strip():
        return copied
    if (
        current_user_index is None
        or isinstance(current_user_index, bool)
        or not 0 <= current_user_index < len(copied)
    ):
        return copied

    target = copied[current_user_index]
    if target.get("role") != "user":
        return copied
    content = target.get("content", "")
    updated = _append_context(content, context.strip())
    if updated is content:
        return copied
    target["content"] = updated
    return copied


def locate_and_clear_experience_target(
    messages: Sequence[Mapping[str, Any]],
    *,
    marker: str,
) -> int | None:
    """Find one marked current-user message and remove all private markers.

    Prompt-cache transforms may deep-copy the API message list, so object
    identity cannot locate the current turn reliably. A per-turn opaque marker
    survives those copies. This helper always strips the private key before
    provider serialization and fails closed if the marker is absent,
    duplicated, or attached to a non-user message.
    """

    if not isinstance(marker, str) or not marker:
        return None
    matches: list[int] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        value = message.pop(_EXPERIENCE_TARGET_KEY, None)
        if value == marker and message.get("role") == "user":
            matches.append(index)
    return matches[0] if len(matches) == 1 else None


__all__ = [
    "ExperienceMode",
    "ExperienceRuntimeTurn",
    "ProviderIdentity",
    "TurnOrigin",
    "copy_messages_with_experience_context",
    "locate_and_clear_experience_target",
    "normalize_experience_mode",
    "normalize_turn_origin",
    "prepare_experience_turn",
    "provider_identity",
]
