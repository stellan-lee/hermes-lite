from __future__ import annotations

import sys
import threading
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import gateway.run as gateway_run
from gateway.config import AdminApprovalConfig, Platform
from gateway.run import (
    _telegram_digital_twin_context,
    _work_experience_turn_kwargs,
)
from gateway.session import SessionSource


def _source(
    *,
    platform: Platform = Platform.TELEGRAM,
    chat_type: str = "dm",
    user_id: str | None = "12345",
    chat_id: str = "12345",
    thread_id: str | None = None,
) -> SessionSource:
    return SessionSource(
        platform=platform,
        chat_id=chat_id,
        chat_type=chat_type,
        user_id=user_id,
        thread_id=thread_id,
    )


def test_telegram_owner_dm_supplies_explicit_experience_boundary() -> None:
    assert _work_experience_turn_kwargs(
        _source(),
        "Please diagnose the failed deploy",
    ) == {
        "raw_user_message": "Please diagnose the failed deploy",
        "turn_origin": "telegram",
    }


@pytest.mark.parametrize(
    ("source", "raw_user_message"),
    [
        (_source(platform=Platform.SLACK), "request"),
        (_source(chat_type="group"), "request"),
        (_source(chat_type="channel"), "request"),
        (_source(user_id=None), "request"),
        (_source(), None),
        (_source(), "   "),
    ],
)
def test_other_gateway_turns_do_not_supply_experience_boundary(
    source: SessionSource,
    raw_user_message: str | None,
) -> None:
    assert _work_experience_turn_kwargs(source, raw_user_message) == {}


def test_telegram_guest_turn_supplies_explicit_experience_boundary() -> None:
    source = _source(chat_type="group", user_id=None, chat_id="guest-chat")

    assert _work_experience_turn_kwargs(
        source,
        "Please help with this deployment",
        telegram_digital_twin_guest=True,
    ) == {
        "raw_user_message": "Please help with this deployment",
        "turn_origin": "telegram_guest",
    }


def test_every_non_super_admin_telegram_source_resolves_as_digital_twin() -> None:
    config = {
        "experience": {
            "telegram_digital_twin": {
                "enabled": True,
                "system_prompt": "Global guest prompt",
            }
        }
    }
    admin = AdminApprovalConfig(
        enabled=True,
        conversation_mode="super_admin",
        platform=Platform.TELEGRAM,
        user_id="admin-user",
        chat_id="admin-chat",
        thread_id="admin-topic",
    )

    exact_admin = _telegram_digital_twin_context(
        _source(
            user_id="admin-user",
            chat_id="admin-chat",
            thread_id="admin-topic",
        ),
        config,
        admin,
        is_super_admin_source=True,
    )
    sibling_topic = _telegram_digital_twin_context(
        _source(chat_type="group", chat_id="admin-chat", thread_id="other-topic"),
        config,
        admin,
        is_super_admin_source=False,
    )
    other_chat = _telegram_digital_twin_context(
        _source(chat_type="group", chat_id="guest-chat"),
        config,
        admin,
        is_super_admin_source=False,
    )

    assert exact_admin.enabled is False
    assert sibling_topic.enabled is True
    assert sibling_topic.system_prompt == "Global guest prompt"
    assert other_chat.enabled is True


def test_non_admin_user_in_super_admin_chat_is_still_a_guest() -> None:
    config = {
        "experience": {
            "telegram_digital_twin": {
                "enabled": True,
            }
        }
    }
    admin = AdminApprovalConfig(
        enabled=True,
        conversation_mode="super_admin",
        platform=Platform.TELEGRAM,
        user_id="admin-user",
        chat_id="admin-chat",
    )

    exact_admin = _telegram_digital_twin_context(
        _source(
            chat_type="group",
            user_id="admin-user",
            chat_id="admin-chat",
            thread_id="topic-2",
        ),
        config,
        admin,
        is_super_admin_source=True,
    )
    guest_context = _telegram_digital_twin_context(
        _source(
            chat_type="group",
            user_id="guest-user",
            chat_id="admin-chat",
            thread_id="topic-2",
        ),
        config,
        admin,
        is_super_admin_source=False,
    )

    assert exact_admin.enabled is False
    assert guest_context.enabled is True
    assert "digital twin" in guest_context.system_prompt


class _CapturingAgent:
    last_call: tuple[object, dict[str, object]] | None = None
    last_init: dict[str, object] | None = None
    last_guest_role: bool | None = None

    def __init__(self, *args, **kwargs) -> None:
        type(self).last_init = dict(kwargs)
        self.tools = []

    def run_conversation(self, user_message, **kwargs):
        type(self).last_call = (user_message, dict(kwargs))
        type(self).last_guest_role = getattr(
            self,
            "_telegram_digital_twin_guest",
            False,
        )
        return {
            "final_response": "ok",
            "messages": [],
            "api_calls": 1,
            "completed": True,
        }


@pytest.mark.asyncio
async def test_run_agent_keeps_raw_telegram_query_separate_from_wire_message(
    monkeypatch,
    tmp_path,
) -> None:
    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _CapturingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)
    monkeypatch.setattr(gateway_run, "_marlow_home", tmp_path)
    monkeypatch.setattr(gateway_run, "_env_path", tmp_path / ".env")
    monkeypatch.setattr(gateway_run, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: {})
    monkeypatch.setattr(
        gateway_run, "_resolve_gateway_model", lambda config=None: "model"
    )
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        lambda: {
            "provider": "ollama",
            "api_mode": "chat_completions",
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "***",
        },
    )

    import marlow_cli.tools_config as tools_config

    monkeypatch.setattr(
        tools_config,
        "_get_platform_tools",
        lambda user_config, platform_key: {"core"},
    )

    runner = object.__new__(gateway_run.GatewayRunner)
    runner.adapters = {}
    runner._ephemeral_system_prompt = ""
    runner._prefill_messages = []
    runner._reasoning_config = None
    runner._provider_routing = {}
    runner._fallback_providers = None
    runner._running_agents = {}
    runner._pending_model_notes = {}
    runner._session_db = None
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()
    runner._session_model_overrides = {}
    runner.hooks = SimpleNamespace(loaded_hooks=False)
    runner.config = SimpleNamespace(streaming=None)
    runner.session_store = SimpleNamespace()
    runner._get_or_create_gateway_honcho = lambda session_key: (None, None)
    runner._enrich_message_with_vision = AsyncMock(return_value="ENRICHED")

    _CapturingAgent.last_call = None
    result = await runner._run_agent(
        message="[System note]\n\nExpanded user message with /tmp/attachment",
        raw_user_message="Please inspect the attachment",
        context_prompt="",
        history=[],
        source=_source(),
        session_id="session-1",
        session_key="agent:main:telegram:dm:12345",
    )

    assert result["final_response"] == "ok"
    wire_message, call_kwargs = _CapturingAgent.last_call
    assert "Expanded user message" in wire_message
    assert call_kwargs["raw_user_message"] == "Please inspect the attachment"
    assert call_kwargs["turn_origin"] == "telegram"


@pytest.mark.asyncio
async def test_run_agent_composes_guest_and_channel_prompts_and_marks_recall(
    monkeypatch,
    tmp_path,
) -> None:
    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _CapturingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)
    monkeypatch.setattr(gateway_run, "_marlow_home", tmp_path)
    monkeypatch.setattr(gateway_run, "_env_path", tmp_path / ".env")
    monkeypatch.setattr(gateway_run, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {
            "experience": {
                "telegram_digital_twin": {
                    "enabled": True,
                    "system_prompt": "Global guest prompt",
                }
            }
        },
    )
    monkeypatch.setattr(
        gateway_run, "_resolve_gateway_model", lambda config=None: "model"
    )
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        lambda: {
            "provider": "ollama",
            "api_mode": "chat_completions",
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "***",
        },
    )

    import marlow_cli.tools_config as tools_config

    monkeypatch.setattr(
        tools_config,
        "_get_platform_tools",
        lambda user_config, platform_key: {"core"},
    )

    runner = object.__new__(gateway_run.GatewayRunner)
    runner.adapters = {}
    runner._ephemeral_system_prompt = ""
    runner._prefill_messages = []
    runner._reasoning_config = None
    runner._provider_routing = {}
    runner._fallback_providers = None
    runner._running_agents = {}
    runner._pending_model_notes = {}
    runner._session_db = None
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()
    runner._session_model_overrides = {}
    runner.hooks = SimpleNamespace(loaded_hooks=False)
    runner.config = SimpleNamespace(
        streaming=None,
        admin_approval=AdminApprovalConfig(
            enabled=True,
            conversation_mode="super_admin",
            platform=Platform.TELEGRAM,
            user_id="admin-user",
            chat_id="admin-chat",
        ),
    )
    runner.session_store = SimpleNamespace()
    runner._get_or_create_gateway_honcho = lambda session_key: (None, None)
    runner._enrich_message_with_vision = AsyncMock(return_value="ENRICHED")

    source = _source(
        chat_type="group",
        chat_id="guest-chat",
        user_id="guest-user",
    )
    _CapturingAgent.last_call = None
    _CapturingAgent.last_init = None
    _CapturingAgent.last_guest_role = None
    result = await runner._run_agent(
        message="Please help",
        raw_user_message="Please help",
        context_prompt="Telegram context",
        history=[],
        source=source,
        session_id="session-guest",
        session_key="agent:main:telegram:group:guest-chat:guest-user",
        channel_prompt="Channel-specific prompt",
    )

    assert result["final_response"] == "ok"
    assert _CapturingAgent.last_init["ephemeral_system_prompt"] == (
        "Telegram context\n\n"
        "Global guest prompt\n\n"
        "Channel-specific prompt"
    )
    assert _CapturingAgent.last_init["skip_memory"] is True
    assert "memory" in _CapturingAgent.last_init["disabled_toolsets"]
    assert "session_search" in _CapturingAgent.last_init["disabled_toolsets"]
    _, call_kwargs = _CapturingAgent.last_call
    assert call_kwargs["turn_origin"] == "telegram_guest"
    assert call_kwargs["raw_user_message"] == "Please help"
    assert _CapturingAgent.last_guest_role is True
