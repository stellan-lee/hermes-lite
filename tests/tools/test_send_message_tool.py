"""Tests for retained send_message targets and routing."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from gateway.config import Platform
from tools.send_message_tool import (
    _parse_target_ref, _sanitize_error_text, _send_to_platform,
    _telegram_retry_delay, send_message_tool,
)


def test_retained_explicit_target_formats():
    assert _parse_target_ref("telegram", "-100123:42") == ("-100123", "42", True)
    assert _parse_target_ref("discord", "123456789:987654321") == ("123456789", "987654321", True)
    assert _parse_target_ref("slack", "C12345678") == ("C12345678", None, True)
    assert _parse_target_ref("feishu", "oc_chat123:thread_1") == ("oc_chat123", "thread_1", True)
    assert _parse_target_ref("email", "user@example.com") == ("user@example.com", None, True)


def test_unknown_name_requires_directory_resolution():
    assert _parse_target_ref("telegram", "general") == (None, None, False)


def test_error_sanitization_redacts_query_secrets():
    text = _sanitize_error_text("failed https://x.test?a=1&token=secret")
    assert "secret" not in text
    assert "token=***" in text


def test_transient_telegram_retry_policy():
    assert _telegram_retry_delay(RuntimeError("502 Bad Gateway"), 1) == 2.0
    assert _telegram_retry_delay(RuntimeError("invalid chat"), 0) is None


def test_list_action_uses_channel_directory():
    with patch("gateway.channel_directory.format_directory_for_display", return_value="targets"):
        result = send_message_tool({"action": "list"})
    assert "targets" in result


def test_send_requires_target_and_message():
    result = send_message_tool({"action": "send", "target": "telegram"})
    assert "required" in result.lower()


def test_telegram_routes_to_native_sender():
    cfg = SimpleNamespace(token="token", extra={})
    sender = AsyncMock(return_value={"success": True, "platform": "telegram"})
    with patch("tools.send_message_tool._send_telegram", sender):
        result = asyncio.run(_send_to_platform(Platform.TELEGRAM, cfg, "123", "hello"))
    assert result["success"] is True
    sender.assert_awaited_once()


def test_slack_routes_to_native_sender():
    cfg = SimpleNamespace(token="token", extra={})
    sender = AsyncMock(return_value={"success": True, "platform": "slack"})
    with patch("tools.send_message_tool._send_slack", sender):
        result = asyncio.run(_send_to_platform(Platform.SLACK, cfg, "C12345678", "hello"))
    assert result["success"] is True
    sender.assert_awaited_once()


def test_email_routes_to_native_sender():
    cfg = SimpleNamespace(token="", extra={})
    sender = AsyncMock(return_value={"success": True, "platform": "email"})
    with patch("tools.send_message_tool._send_email", sender):
        result = asyncio.run(_send_to_platform(Platform.EMAIL, cfg, "u@example.com", "hello"))
    assert result["success"] is True
    sender.assert_awaited_once()


def test_feishu_routes_to_native_sender():
    cfg = SimpleNamespace(token="", extra={})
    sender = AsyncMock(return_value={"success": True, "platform": "feishu"})
    with patch("tools.send_message_tool._send_feishu", sender):
        result = asyncio.run(_send_to_platform(Platform.FEISHU, cfg, "oc_test", "hello"))
    assert result["success"] is True
    sender.assert_awaited_once()
