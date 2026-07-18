"""OpenAI Chat Completions transport.

Handles the default api_mode (``chat_completions``) for custom and local
OpenAI-compatible endpoints.

Messages and tools are already in OpenAI format — convert_messages and
convert_tools are near-identity.  The complexity lives in build_kwargs
which has provider-specific conditionals for max_tokens defaults,
reasoning configuration, temperature handling, and extra_body assembly.
"""

import copy
from typing import Any, Dict

from agent.lmstudio_reasoning import resolve_lmstudio_effort
from agent.prompt_builder import DEVELOPER_ROLE_MODELS
from agent.transports.base import ProviderTransport
from agent.transports.types import NormalizedResponse, ToolCall, Usage


class ChatCompletionsTransport(ProviderTransport):
    """Transport for api_mode='chat_completions'.

    The default path for OpenAI-compatible providers.
    """

    @property
    def api_mode(self) -> str:
        return "chat_completions"

    def convert_messages(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> list[dict[str, Any]]:
        """Messages are already in OpenAI format — strip internal fields
        that strict chat-completions providers reject with HTTP 400/422
        (or, in the case of some OpenAI-compatible gateways, 5xx):

        - Codex Responses API fields: ``codex_reasoning_items`` /
          ``codex_message_items`` on the message, ``call_id`` /
          ``response_item_id`` on ``tool_calls`` entries.
        - ``tool_name`` on tool-result messages — written by
          ``make_tool_result_message()`` for the SQLite FTS index, but not
          part of the Chat Completions schema. Strict providers (Fireworks,
          Moonshot/Kimi) reject any payload containing it with
          ``Extra inputs are not permitted, field: 'messages[N].tool_name'``.
          Permissive providers (OpenRouter, MiniMax) silently ignore the
          field, which masked the bug for months.
        - Hermes-internal scaffolding markers — any top-level message key
          starting with ``_`` (e.g. ``_empty_recovery_synthetic``,
          ``_empty_terminal_sentinel``, ``_thinking_prefill``). These are
          bookkeeping flags the agent loop attaches to messages so the
          persistence layer can later strip its own scaffolding; they must
          never reach the wire. Permissive providers (real OpenAI,
          Anthropic) silently drop unknown message keys, but strict
          gateways (e.g. opencode-go, codex.nekos.me) reject with
          ``Extra inputs are not permitted, field: 'messages[N]._empty_recovery_synthetic'``,
          which then poisons every subsequent request in the session.
        """
        needs_sanitize = False
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if (
                "codex_reasoning_items" in msg
                or "codex_message_items" in msg
                or "tool_name" in msg
            ):
                needs_sanitize = True
                break
            if any(isinstance(k, str) and k.startswith("_") for k in msg):
                needs_sanitize = True
                break
            tool_calls = msg.get("tool_calls")
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    if isinstance(tc, dict) and (
                        "call_id" in tc or "response_item_id" in tc
                    ):
                        needs_sanitize = True
                        break
                if needs_sanitize:
                    break

        if not needs_sanitize:
            return messages

        sanitized = copy.deepcopy(messages)
        for msg in sanitized:
            if not isinstance(msg, dict):
                continue
            msg.pop("codex_reasoning_items", None)
            msg.pop("codex_message_items", None)
            msg.pop("tool_name", None)
            # Drop all Hermes-internal scaffolding markers (``_``-prefixed).
            # OpenAI's message schema has no ``_``-prefixed fields, so this
            # is safe and future-proofs against new markers being added.
            for key in [k for k in msg if isinstance(k, str) and k.startswith("_")]:
                msg.pop(key, None)
            tool_calls = msg.get("tool_calls")
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        tc.pop("call_id", None)
                        tc.pop("response_item_id", None)
        return sanitized

    def convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Tools are already in OpenAI format — identity."""
        return tools

    def build_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **params,
    ) -> dict[str, Any]:
        """Build chat.completions.create() kwargs.

        params (all optional):
            timeout: float — API call timeout
            max_tokens: int | None — user-configured max tokens
            ephemeral_max_output_tokens: int | None — one-shot override
            max_tokens_param_fn: callable — returns {max_tokens: N} or {max_completion_tokens: N}
            reasoning_config: dict | None
            request_overrides: dict | None
            session_id: str | None
            model_lower: str — lowercase model name for pattern matching
            # Provider profile path (all per-provider quirks live in providers/)
            provider_profile: ProviderProfile | None — when present, delegates to
                _build_kwargs_from_profile(); all flag params below are bypassed.
            # Retained compatible-runtime flags
            is_lmstudio: bool
            is_custom_provider: bool
            ollama_num_ctx: int | None
            # Temperature
            fixed_temperature: Any — from _fixed_temperature_for_model()
            omit_temperature: bool
            # Reasoning
            supports_reasoning: bool
            lmstudio_reasoning_options: list[str] | None  # raw allowed_options from /api/v1/models
            extra_body_additions: dict | None
        """
        # Codex sanitization: drop reasoning_items / call_id / response_item_id
        sanitized = self.convert_messages(messages)

        # ── Provider profile: single-path when present ──────────────────
        _profile = params.get("provider_profile")
        if _profile:
            return self._build_kwargs_from_profile(
                _profile, model, sanitized, tools, params
            )

        # ── Legacy fallback (unregistered / unknown provider) ───────────
        # Reached only when get_provider_profile() returned None.
        # Known providers always go through the profile path above.

        # Developer role swap for GPT-5/Codex models
        model_lower = params.get("model_lower", (model or "").lower())
        if (
            sanitized
            and isinstance(sanitized[0], dict)
            and sanitized[0].get("role") == "system"
            and any(p in model_lower for p in DEVELOPER_ROLE_MODELS)
        ):
            sanitized = list(sanitized)
            sanitized[0] = {**sanitized[0], "role": "developer"}

        api_kwargs: dict[str, Any] = {
            "model": model,
            "messages": sanitized,
        }

        timeout = params.get("timeout")
        if timeout is not None:
            api_kwargs["timeout"] = timeout

        # Tools are already OpenAI-compatible schemas.
        if tools:
            api_kwargs["tools"] = tools

        # max_tokens resolution — priority: ephemeral > user > provider default
        max_tokens_fn = params.get("max_tokens_param_fn")
        ephemeral = params.get("ephemeral_max_output_tokens")
        max_tokens = params.get("max_tokens")
        reasoning_config = params.get("reasoning_config")

        if ephemeral is not None and max_tokens_fn:
            api_kwargs.update(max_tokens_fn(ephemeral))
        elif max_tokens is not None and max_tokens_fn:
            api_kwargs.update(max_tokens_fn(max_tokens))

        # LM Studio: top-level reasoning_effort. Only emit when the model
        # declares reasoning support via /api/v1/models capabilities (gated
        # upstream by params["supports_reasoning"]). resolve_lmstudio_effort
        # is shared with run_agent's summary path so both stay in sync.
        if params.get("is_lmstudio", False) and params.get("supports_reasoning", False):
            _lm_effort = resolve_lmstudio_effort(
                reasoning_config,
                params.get("lmstudio_reasoning_options"),
            )
            if _lm_effort is not None:
                api_kwargs["reasoning_effort"] = _lm_effort

        # extra_body assembly
        extra_body: dict[str, Any] = {}

        # Reasoning. LM Studio is handled above via top-level reasoning_effort,
        # so skip emitting extra_body.reasoning for it.
        if params.get("supports_reasoning", False) and not params.get("is_lmstudio", False):
            extra_body["reasoning"] = {"enabled": True, "effort": "medium"}

        # Merge any pre-built extra_body additions
        additions = params.get("extra_body_additions")
        if additions:
            extra_body.update(additions)

        if extra_body:
            api_kwargs["extra_body"] = extra_body

        # Request overrides are applied last.
        overrides = params.get("request_overrides")
        if overrides:
            api_kwargs.update(overrides)

        return api_kwargs

    def _build_kwargs_from_profile(self, profile, model, sanitized, tools, params):
        """Build API kwargs using a ProviderProfile — single path, no legacy flags.

        This method replaces the entire flag-based kwargs assembly when a
        provider_profile is passed. Every quirk comes from the profile object.
        """
        from providers.base import OMIT_TEMPERATURE

        # Message preprocessing
        sanitized = profile.prepare_messages(sanitized)

        # Developer role swap — model-name-based, applies to all providers
        _model_lower = (model or "").lower()
        if (
            sanitized
            and isinstance(sanitized[0], dict)
            and sanitized[0].get("role") == "system"
            and any(p in _model_lower for p in DEVELOPER_ROLE_MODELS)
        ):
            sanitized = list(sanitized)
            sanitized[0] = {**sanitized[0], "role": "developer"}

        api_kwargs: dict[str, Any] = {
            "model": model,
            "messages": sanitized,
        }

        # Temperature
        if profile.fixed_temperature is OMIT_TEMPERATURE:
            pass  # Don't include temperature at all
        elif profile.fixed_temperature is not None:
            api_kwargs["temperature"] = profile.fixed_temperature
        else:
            # Use caller's temperature if provided
            temp = params.get("temperature")
            if temp is not None:
                api_kwargs["temperature"] = temp

        # Timeout
        timeout = params.get("timeout")
        if timeout is not None:
            api_kwargs["timeout"] = timeout

        # Tools are already OpenAI-compatible schemas.
        if tools:
            api_kwargs["tools"] = tools

        # max_tokens resolution — priority: ephemeral > user > profile default
        max_tokens_fn = params.get("max_tokens_param_fn")
        ephemeral = params.get("ephemeral_max_output_tokens")
        user_max = params.get("max_tokens")
        # Per-model default cap — profiles override get_max_tokens() when
        # they front several backends with different completion-token limits
        # (e.g. opencode-go: mimo-v2.5-pro = 131072).
        profile_max = profile.get_max_tokens(model)

        if ephemeral is not None and max_tokens_fn:
            api_kwargs.update(max_tokens_fn(ephemeral))
        elif user_max is not None and max_tokens_fn:
            api_kwargs.update(max_tokens_fn(user_max))
        elif profile_max and max_tokens_fn:
            api_kwargs.update(max_tokens_fn(profile_max))

        # Provider-specific api_kwargs extras (reasoning_effort, metadata, etc.)
        reasoning_config = params.get("reasoning_config")
        extra_body_from_profile, top_level_from_profile = (
            profile.build_api_kwargs_extras(
                reasoning_config=reasoning_config,
                supports_reasoning=params.get("supports_reasoning", False),
                model=model,
                ollama_num_ctx=params.get("ollama_num_ctx"),
                session_id=params.get("session_id"),
            )
        )
        api_kwargs.update(top_level_from_profile)

        # extra_body assembly
        extra_body: dict[str, Any] = {}

        # Profile's extra_body (tags, provider prefs, vl_high_resolution, etc.)
        profile_body = profile.build_extra_body(
            session_id=params.get("session_id"),
            model=model,
            base_url=params.get("base_url"),
            reasoning_config=reasoning_config,
        )
        if profile_body:
            extra_body.update(profile_body)

        # Profile's reasoning/thinking extra_body entries
        if extra_body_from_profile:
            extra_body.update(extra_body_from_profile)

        # Merge any pre-built extra_body additions from the caller
        additions = params.get("extra_body_additions")
        if additions:
            extra_body.update(additions)

        # Request overrides (user config)
        overrides = params.get("request_overrides")
        if overrides:
            for k, v in overrides.items():
                if k == "extra_body" and isinstance(v, dict):
                    extra_body.update(v)
                else:
                    api_kwargs[k] = v

        if extra_body:
            api_kwargs["extra_body"] = extra_body

        return api_kwargs

    def normalize_response(self, response: Any, **kwargs) -> NormalizedResponse:
        """Normalize OpenAI ChatCompletion to NormalizedResponse.

        For chat_completions, this is near-identity — the response is already
        in OpenAI format.  extra_content on tool_calls (Gemini thought_signature)
        is preserved via ToolCall.provider_data.  reasoning_details (OpenRouter
        unified format) and reasoning_content (DeepSeek/Moonshot) are also
        preserved for downstream replay.
        """
        choice = response.choices[0]
        msg = choice.message
        finish_reason = choice.finish_reason or "stop"

        tool_calls = None
        if msg.tool_calls:
            tool_calls = []
            for tc in msg.tool_calls:
                # Preserve provider-specific extras on the tool call.
                # Gemini 3 thinking models attach extra_content with
                # thought_signature — without replay on the next turn the API
                # rejects the request with 400.
                tc_provider_data: dict[str, Any] = {}
                extra = getattr(tc, "extra_content", None)
                if extra is None and hasattr(tc, "model_extra"):
                    extra = (tc.model_extra or {}).get("extra_content")
                if extra is not None:
                    if hasattr(extra, "model_dump"):
                        try:
                            extra = extra.model_dump()
                        except Exception:
                            pass
                    tc_provider_data["extra_content"] = extra
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=tc.function.arguments,
                        provider_data=tc_provider_data or None,
                    )
                )

        usage = None
        if hasattr(response, "usage") and response.usage:
            u = response.usage
            usage = Usage(
                prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(u, "completion_tokens", 0) or 0,
                total_tokens=getattr(u, "total_tokens", 0) or 0,
            )

        # Preserve reasoning fields separately.  DeepSeek/Moonshot use
        # ``reasoning_content``; others use ``reasoning``.  Downstream code
        # (_extract_reasoning, thinking-prefill retry) reads both distinctly,
        # so keep them apart in provider_data rather than merging.
        reasoning = getattr(msg, "reasoning", None)
        reasoning_content = getattr(msg, "reasoning_content", None)
        if reasoning_content is None and hasattr(msg, "model_extra"):
            model_extra = getattr(msg, "model_extra", None) or {}
            if isinstance(model_extra, dict) and "reasoning_content" in model_extra:
                reasoning_content = model_extra["reasoning_content"]

        provider_data: Dict[str, Any] = {}
        if reasoning_content is not None:
            provider_data["reasoning_content"] = reasoning_content
        rd = getattr(msg, "reasoning_details", None)
        if rd:
            provider_data["reasoning_details"] = rd

        return NormalizedResponse(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            reasoning=reasoning,
            usage=usage,
            provider_data=provider_data or None,
        )

    def validate_response(self, response: Any) -> bool:
        """Check that response has valid choices."""
        if response is None:
            return False
        if not hasattr(response, "choices") or response.choices is None:
            return False
        if not response.choices:
            return False
        return True

    def extract_cache_stats(self, response: Any) -> dict[str, int] | None:
        """Extract OpenRouter/OpenAI cache stats from prompt_tokens_details."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        details = getattr(usage, "prompt_tokens_details", None)
        if details is None:
            return None
        cached = getattr(details, "cached_tokens", 0) or 0
        written = getattr(details, "cache_write_tokens", 0) or 0
        if cached or written:
            return {"cached_tokens": cached, "creation_tokens": written}
        return None


# Auto-register on import
from agent.transports import register_transport  # noqa: E402

register_transport("chat_completions", ChatCompletionsTransport)
