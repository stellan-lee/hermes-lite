"""Security and persistence tests for Telegram in-chat group grants."""

from __future__ import annotations

import json
import stat
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.group_access import GroupAccessStore
from gateway.platforms.base import MessageEvent, MessageType
from gateway.session import SessionSource


def _source(
    *,
    user_id: str = "100",
    chat_id: str = "-1001",
    chat_type: str = "group",
    platform: Platform = Platform.TELEGRAM,
) -> SessionSource:
    return SessionSource(
        platform=platform,
        chat_id=chat_id,
        chat_type=chat_type,
        user_id=user_id,
        user_name=f"user-{user_id}",
    )


def _event(
    text: str,
    *,
    source: SessionSource | None = None,
    reply_user: SimpleNamespace | None = None,
) -> MessageEvent:
    reply = None
    if reply_user is not None:
        reply = SimpleNamespace(
            message_id=41,
            from_user=reply_user,
            text="hello",
            caption=None,
        )
    raw_message = SimpleNamespace(reply_to_message=reply)
    return MessageEvent(
        text=text,
        message_type=MessageType.COMMAND,
        source=source or _source(),
        raw_message=raw_message,
        message_id="42",
    )


def _runner(store: GroupAccessStore, *, is_admin: bool = True):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={
            Platform.TELEGRAM: PlatformConfig(enabled=True, token="test")
        }
    )
    adapter = SimpleNamespace(
        is_group_administrator=AsyncMock(return_value=is_admin),
        enforces_own_access_policy=False,
    )
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner.group_access_store = store
    runner.pairing_store = MagicMock()
    runner.pairing_store.is_approved.return_value = False
    return runner, adapter


def _clear_auth_env(monkeypatch) -> None:
    for name in (
        "TELEGRAM_ALLOWED_USERS",
        "TELEGRAM_GROUP_ALLOWED_USERS",
        "TELEGRAM_GROUP_ALLOWED_CHATS",
        "TELEGRAM_ALLOW_ALL_USERS",
        "GATEWAY_ALLOWED_USERS",
        "GATEWAY_ALLOW_ALL_USERS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_store_persists_owner_only_group_scoped_grants(tmp_path):
    path = tmp_path / "telegram" / "group-access.json"
    store = GroupAccessStore(path)

    assert store.grant(
        "telegram",
        "-1001",
        "200",
        user_name="Alice",
        granted_by="100",
        granted_by_name="Admin",
    ) is True

    reloaded = GroupAccessStore(path)
    assert reloaded.is_granted("telegram", "-1001", "200") is True
    assert reloaded.is_granted("telegram", "-1002", "200") is False
    assert reloaded.is_granted("telegram", "200", "200") is False
    if not sys.platform.startswith("win"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert reloaded.list_grants("telegram", "-1001")[0]["user_name"] == "Alice"

    assert reloaded.revoke("telegram", "-1001", "200") is True
    assert reloaded.is_granted("telegram", "-1001", "200") is False


def test_store_recovers_from_malformed_data(tmp_path):
    path = tmp_path / "group-access.json"
    path.write_text("{not-json", encoding="utf-8")
    store = GroupAccessStore(path)

    assert store.list_grants("telegram", "-1001") == []
    assert store.grant(
        "telegram", "-1001", "200", granted_by="100"
    ) is True
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


@pytest.mark.asyncio
async def test_admin_can_grant_by_reply_and_authorization_is_immediate(
    tmp_path, monkeypatch
):
    _clear_auth_env(monkeypatch)
    store = GroupAccessStore(tmp_path / "group-access.json")
    runner, adapter = _runner(store)
    reply_user = SimpleNamespace(id=200, full_name="Alice Example", username="alice")

    result = await runner._handle_access_command(
        _event("/access grant", reply_user=reply_user)
    )

    assert "Granted Alice Example access" in result
    adapter.is_group_administrator.assert_awaited_once_with("-1001", "100")
    assert runner._is_user_authorized(_source(user_id="200")) is True
    assert runner._is_user_authorized(
        _source(user_id="200", chat_id="-1002")
    ) is False


@pytest.mark.asyncio
async def test_unauthorized_admin_access_command_reaches_verified_handler(
    tmp_path, monkeypatch
):
    """Exercise the real pre-auth and slash-dispatch path end to end."""
    _clear_auth_env(monkeypatch)
    monkeypatch.setattr("marlow_cli.plugins.invoke_hook", lambda *_a, **_kw: [])
    store = GroupAccessStore(tmp_path / "group-access.json")
    runner, _adapter = _runner(store)
    runner.session_store = MagicMock()
    runner._update_prompt_pending = {}
    runner._running_agents = {}
    runner.hooks = SimpleNamespace(emit_collect=AsyncMock(return_value=[]))
    reply_user = SimpleNamespace(id=200, full_name="Alice", username="alice")

    result = await runner._handle_message(
        _event("/access grant", reply_user=reply_user)
    )

    assert "Granted Alice access" in result
    assert store.is_granted("telegram", "-1001", "200") is True


@pytest.mark.asyncio
async def test_non_admin_cannot_grant_access(tmp_path):
    store = GroupAccessStore(tmp_path / "group-access.json")
    runner, _adapter = _runner(store, is_admin=False)
    reply_user = SimpleNamespace(id=200, full_name="Alice", username="alice")

    result = await runner._handle_access_command(
        _event("/access grant", reply_user=reply_user)
    )

    assert "Only a verified Telegram group administrator" in result
    assert store.is_granted("telegram", "-1001", "200") is False


@pytest.mark.asyncio
async def test_revoke_and_list_are_scoped_to_current_group(tmp_path):
    store = GroupAccessStore(tmp_path / "group-access.json")
    store.grant("telegram", "-1001", "200", user_name="Alice", granted_by="100")
    store.grant("telegram", "-1002", "300", user_name="Bob", granted_by="100")
    runner, _adapter = _runner(store)

    listed = await runner._handle_access_command(_event("/access list"))
    revoked = await runner._handle_access_command(_event("/access revoke 200"))

    assert "Alice" in listed
    assert "Bob" not in listed
    assert "Revoked" in revoked
    assert store.is_granted("telegram", "-1001", "200") is False
    assert store.is_granted("telegram", "-1002", "300") is True


@pytest.mark.asyncio
async def test_access_rejects_dm_username_and_unavailable_verification(tmp_path):
    store = GroupAccessStore(tmp_path / "group-access.json")
    runner, _adapter = _runner(store)

    dm_result = await runner._handle_access_command(
        _event("/access grant 200", source=_source(chat_type="dm", chat_id="100"))
    )
    username_result = await runner._handle_access_command(
        _event("/access grant @alice")
    )
    runner.adapters[Platform.TELEGRAM] = SimpleNamespace()
    unavailable_result = await runner._handle_access_command(
        _event("/access grant 200")
    )

    assert "only inside Telegram groups" in dm_result
    assert "usernames cannot be resolved" in username_result
    assert "verification is unavailable" in unavailable_result


def test_only_exact_telegram_group_access_command_gets_bootstrap_path():
    from gateway.run import GatewayRunner

    event = _event("/access@my_bot grant 200")
    event.raw_user_message = "/access@my_bot grant 200"
    assert GatewayRunner._is_telegram_group_access_command(event) is True

    event.text = "/stop"
    assert GatewayRunner._is_telegram_group_access_command(event) is False

    event = _event("/access grant 200", source=_source(chat_type="dm", chat_id="100"))
    assert GatewayRunner._is_telegram_group_access_command(event) is False

    event = _event(
        "/access grant 200",
        source=_source(platform=Platform.DISCORD),
    )
    assert GatewayRunner._is_telegram_group_access_command(event) is False


@pytest.mark.asyncio
async def test_telegram_admin_verification_accepts_admin_and_fails_closed():
    from gateway.platforms.telegram import TelegramAdapter

    adapter = object.__new__(TelegramAdapter)
    adapter.platform = Platform.TELEGRAM
    adapter._bot = SimpleNamespace(
        id=999,
        get_chat_member=AsyncMock(
            side_effect=[
                SimpleNamespace(status="administrator"),
                SimpleNamespace(status="administrator"),
            ]
        )
    )
    adapter.config = PlatformConfig(enabled=True, token="test")
    assert await adapter.is_group_administrator("-1001", "100") is True

    adapter._bot.get_chat_member.side_effect = [
        SimpleNamespace(status="administrator"),
        SimpleNamespace(status="member"),
    ]
    assert await adapter.is_group_administrator("-1001", "100") is False

    adapter._bot.get_chat_member.side_effect = RuntimeError("forbidden")
    assert await adapter.is_group_administrator("-1001", "100") is False

    adapter._bot.get_chat_member.side_effect = [SimpleNamespace(status="member")]
    assert await adapter.is_group_administrator("-1001", "100") is False
