"""Security and concurrency tests for routed administrator approvals."""

import json
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gateway.config import AdminApprovalConfig, GatewayConfig, Platform
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource


def _clear_approval_state() -> None:
    from tools import approval

    approval._gateway_queues.clear()
    approval._gateway_notify_cbs.clear()
    approval._session_approved.clear()
    approval._session_yolo.clear()
    approval._permanent_approved.clear()
    approval._pending.clear()


class _Adapter:
    pass


def _runner(admin: AdminApprovalConfig):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(admin_approval=admin)
    runner.adapters = {}
    runner._pending_approvals = {}
    return runner


def _event(
    text: str,
    *,
    platform: Platform = Platform.TELEGRAM,
    user_id: str = "admin-user",
    chat_id: str = "admin-chat",
    thread_id: str | None = "admin-thread",
) -> MessageEvent:
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform=platform,
            user_id=user_id,
            chat_id=chat_id,
            thread_id=thread_id,
        ),
        message_id="message-1",
    )


class TestAdminApprovalConfig:
    def test_round_trip_and_completeness(self):
        config = AdminApprovalConfig.from_dict(
            {
                "enabled": True,
                "platform": "telegram",
                "user_id": "  admin-user  ",
                "chat_id": 1234,
                "thread_id": 99,
            }
        )

        assert config.is_complete is True
        assert config.platform is Platform.TELEGRAM
        assert config.to_dict() == {
            "enabled": True,
            "platform": "telegram",
            "user_id": "admin-user",
            "chat_id": "1234",
            "thread_id": "99",
        }

    def test_invalid_platform_is_incomplete(self):
        config = AdminApprovalConfig.from_dict(
            {
                "enabled": True,
                "platform": "not-a-platform",
                "user_id": "admin-user",
                "chat_id": "admin-chat",
            }
        )

        assert config.platform is None
        assert config.is_complete is False

    def test_top_level_yaml_is_loaded_into_gateway_runtime(self, tmp_path):
        from gateway import config as gateway_config

        (tmp_path / "config.yaml").write_text(
            """
approvals:
  admin:
    enabled: true
    platform: slack
    user_id: U_ADMIN
    chat_id: C_ADMIN
    thread_id: '171.2'
""".lstrip(),
            encoding="utf-8",
        )

        with patch.object(gateway_config, "get_hermes_home", return_value=tmp_path):
            config = gateway_config.load_gateway_config()

        assert config.admin_approval == AdminApprovalConfig(
            enabled=True,
            platform=Platform.SLACK,
            user_id="U_ADMIN",
            chat_id="C_ADMIN",
            thread_id="171.2",
        )

class TestAdminApprovalQueue:
    def setup_method(self):
        _clear_approval_state()

    def teardown_method(self):
        _clear_approval_state()

    def test_concurrent_requests_resolve_by_id_and_reject_broad_grants(self):
        from tools.approval import (
            register_gateway_notify,
            request_admin_approval,
            resolve_gateway_approval,
            reset_current_session_key,
            set_current_session_key,
        )

        session_key = "agent:main:telegram:dm:user"
        payloads: list[dict] = []
        payloads_ready = threading.Event()
        payloads_lock = threading.Lock()
        results: dict[str, dict] = {}

        def notify(payload: dict) -> None:
            with payloads_lock:
                payloads.append(dict(payload))
                if len(payloads) == 2:
                    payloads_ready.set()

        def request(action: str) -> None:
            token = set_current_session_key(session_key)
            try:
                results[action] = request_admin_approval(action, "test reason")
            finally:
                reset_current_session_key(token)

        register_gateway_notify(session_key, notify)
        first = threading.Thread(target=request, args=("first action",))
        second = threading.Thread(target=request, args=("second action",))
        first.start()
        second.start()

        assert payloads_ready.wait(timeout=3)
        by_action = {payload["command"]: payload for payload in payloads}
        first_id = by_action["first action"]["request_id"]
        second_id = by_action["second action"]["request_id"]
        assert first_id != second_id
        assert by_action["first action"]["allowed_choices"] == ["once", "deny"]
        assert by_action["first action"]["request_scoped_only"] is True

        # Admin requests cannot be resolved by legacy FIFO calls and never
        # create a session-wide or permanent grant.
        assert resolve_gateway_approval(session_key, "once") == 0
        assert resolve_gateway_approval(
            session_key, "always", request_id=first_id
        ) == 0
        assert first.is_alive()

        # Cards can be answered out of order without resolving the wrong tool.
        assert resolve_gateway_approval(
            session_key, "once", request_id=second_id
        ) == 1
        second.join(timeout=3)
        assert not second.is_alive()
        assert results["second action"]["approved"] is True
        assert first.is_alive()

        assert resolve_gateway_approval(
            session_key, "deny", request_id=first_id
        ) == 1
        first.join(timeout=3)
        assert not first.is_alive()
        assert results["first action"]["approved"] is False
        assert results["first action"]["decision"] == "declined"

    def test_delivery_failure_fails_closed_and_resumes_origin(self):
        from tools.approval import (
            register_gateway_notify,
            request_admin_approval,
            reset_current_session_key,
            set_current_session_key,
        )

        session_key = "agent:main:telegram:dm:user"
        resumed = threading.Event()

        def notify(_payload: dict) -> None:
            raise RuntimeError("admin adapter unavailable")

        notify.on_resolved = resumed.set
        register_gateway_notify(session_key, notify)
        token = set_current_session_key(session_key)
        try:
            result = request_admin_approval("restart production")
        finally:
            reset_current_session_key(token)

        assert result["approved"] is False
        assert result["decision"] == "delivery_failed"
        assert resumed.is_set()

    def test_tool_wrapper_returns_machine_readable_decision(self):
        from tools.admin_approval_tool import admin_approval_tool

        with patch(
            "tools.admin_approval_tool.request_admin_approval",
            return_value={"approved": False, "decision": "declined"},
        ):
            result = json.loads(admin_approval_tool("deploy", "production"))

        assert result == {"approved": False, "decision": "declined"}

    def test_admin_route_overrides_mode_off_yolo_and_prior_grants(self):
        from tools import approval

        session_key = "agent:main:telegram:dm:user"
        token = approval.set_current_session_key(session_key)
        approval.enable_session_yolo(session_key)
        _, pattern_key, _ = approval.detect_dangerous_command(
            "rm -rf /tmp/admin-approval-test"
        )
        approval.approve_session(session_key, pattern_key)
        seen = []

        def notify(payload):
            seen.append(dict(payload))
            approval.resolve_gateway_approval(
                session_key,
                "once",
                request_id=payload["request_id"],
            )

        approval.register_gateway_notify(session_key, notify)
        try:
            with (
                patch.object(approval, "_is_gateway_approval_context", return_value=True),
                patch.object(
                    approval,
                    "_get_approval_config",
                    return_value={
                        "mode": "off",
                        "admin": {"enabled": True},
                    },
                ),
                patch(
                    "tools.tirith_security.check_command_security",
                    return_value={"action": "allow", "findings": [], "summary": ""},
                ),
            ):
                result = approval.check_all_command_guards(
                    "rm -rf /tmp/admin-approval-test",
                    "local",
                )
        finally:
            approval.unregister_gateway_notify(session_key)
            approval.disable_session_yolo(session_key)
            approval.reset_current_session_key(token)

        assert result["approved"] is True
        assert result["user_approved"] is True
        assert len(seen) == 1

    def test_admin_route_overrides_smart_auto_approval_for_execute_code(self):
        from tools import approval

        session_key = "agent:main:telegram:dm:user"
        token = approval.set_current_session_key(session_key)
        seen = []

        def notify(payload):
            seen.append(dict(payload))
            approval.resolve_gateway_approval(
                session_key,
                "once",
                request_id=payload["request_id"],
            )

        approval.register_gateway_notify(session_key, notify)
        try:
            with (
                patch.object(approval, "_is_gateway_approval_context", return_value=True),
                patch.object(
                    approval,
                    "_get_approval_config",
                    return_value={
                        "mode": "smart",
                        "admin": {"enabled": True},
                    },
                ),
                patch.object(approval, "_smart_approve", return_value="approve") as smart,
            ):
                result = approval.check_execute_code_guard("print('hello')", "local")
        finally:
            approval.unregister_gateway_notify(session_key)
            approval.reset_current_session_key(token)

        assert result["approved"] is True
        assert result["user_approved"] is True
        assert len(seen) == 1
        smart.assert_not_called()

    def test_admin_mode_overrides_yolo_mode_off_and_prior_grants(self):
        from tools import approval

        session_key = "agent:main:telegram:dm:user"
        token = approval.set_current_session_key(session_key)
        approval.enable_session_yolo(session_key)
        approval.approve_session(session_key, "recursive delete")
        try:
            with (
                patch.object(approval, "_is_gateway_approval_context", return_value=True),
                patch.object(
                    approval,
                    "_get_approval_config",
                    return_value={
                        "mode": "off",
                        "admin": {"enabled": True},
                    },
                ),
            ):
                result = approval.check_all_command_guards(
                    "rm -rf /tmp/admin-review-required",
                    "local",
                )
        finally:
            approval.reset_current_session_key(token)

        assert result["approved"] is False
        assert result["approval_pending"] is True


class TestAdminApprovalRouting:
    def test_routes_to_exact_configured_admin_destination(self):
        admin = AdminApprovalConfig(
            enabled=True,
            platform=Platform.SLACK,
            user_id="U_ADMIN",
            chat_id="C_ADMIN",
            thread_id="171.2",
        )
        runner = _runner(admin)
        origin_adapter = _Adapter()
        admin_adapter = _Adapter()
        runner.adapters = {Platform.SLACK: admin_adapter}

        route = runner._resolve_approval_delivery_route(
            origin_adapter=origin_adapter,
            origin_chat_id="requester-chat",
            origin_metadata=None,
            kind="command",
        )

        assert route == {
            "adapter": admin_adapter,
            "chat_id": "C_ADMIN",
            "metadata": {"notify": True, "thread_id": "171.2"},
            "authorized_user_id": "U_ADMIN",
            "binary": True,
            "title": "Admin Approval Required",
            "admin_routed": True,
            "admin_platform": Platform.SLACK,
        }

    def test_general_admin_request_never_falls_back_to_requester(self):
        runner = _runner(AdminApprovalConfig(enabled=False))

        with pytest.raises(RuntimeError, match="not enabled"):
            runner._resolve_approval_delivery_route(
                origin_adapter=_Adapter(),
                origin_chat_id="requester-chat",
                origin_metadata=None,
                kind="admin_action",
            )

    def test_enabled_incomplete_route_fails_closed(self):
        runner = _runner(
            AdminApprovalConfig(
                enabled=True,
                platform=Platform.TELEGRAM,
                user_id="admin-user",
                chat_id="",
            )
        )

        with pytest.raises(RuntimeError, match="chat_id is missing"):
            runner._resolve_approval_delivery_route(
                origin_adapter=_Adapter(),
                origin_chat_id="requester-chat",
                origin_metadata=None,
                kind="command",
            )

    def test_disconnected_admin_platform_fails_closed(self):
        runner = _runner(
            AdminApprovalConfig(
                enabled=True,
                platform=Platform.SLACK,
                user_id="admin-user",
                chat_id="admin-chat",
            )
        )

        with pytest.raises(RuntimeError, match="not connected"):
            runner._resolve_approval_delivery_route(
                origin_adapter=_Adapter(),
                origin_chat_id="requester-chat",
                origin_metadata=None,
                kind="command",
            )


class TestAdminApprovalCommands:
    @pytest.mark.asyncio
    async def test_only_configured_admin_can_set_delivery_channel(self):
        admin = AdminApprovalConfig(
            enabled=True,
            platform=Platform.TELEGRAM,
            user_id="admin-user",
            chat_id="old-chat",
        )
        runner = _runner(admin)

        result = await runner._handle_set_admin_channel_command(
            _event("/set-admin-channel", user_id="attacker")
        )

        assert "Only the configured administrator" in result
        assert admin.chat_id == "old-chat"

    @pytest.mark.asyncio
    async def test_configured_admin_can_move_delivery_channel(self):
        admin = AdminApprovalConfig(
            enabled=True,
            platform=Platform.TELEGRAM,
            user_id="admin-user",
            chat_id="old-chat",
        )
        runner = _runner(admin)

        with patch("cli.save_config_value", return_value=True) as save:
            result = await runner._handle_set_admin_channel_command(
                _event("/set-admin-channel")
            )

        assert "Admin approval channel set" in result
        assert admin.chat_id == "admin-chat"
        assert admin.thread_id == "admin-thread"
        save.assert_called_once_with(
            "approvals.admin",
            {
                "enabled": True,
                "platform": "telegram",
                "user_id": "admin-user",
                "chat_id": "admin-chat",
                "thread_id": "admin-thread",
            },
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("command", ["/approve", "/deny"])
    async def test_requester_text_commands_cannot_bypass_admin_controls(self, command):
        runner = _runner(
            AdminApprovalConfig(
                enabled=True,
                platform=Platform.TELEGRAM,
                user_id="admin-user",
                chat_id="admin-chat",
            )
        )

        if command == "/approve":
            result = await runner._handle_approve_command(
                _event(command, user_id="requester", chat_id="requester-chat")
            )
        else:
            result = await runner._handle_deny_command(
                _event(command, user_id="requester", chat_id="requester-chat")
            )

        assert "Admin-routed approvals" in result

    @pytest.mark.asyncio
    async def test_yolo_is_disabled_while_admin_routing_is_enabled(self):
        runner = _runner(
            AdminApprovalConfig(
                enabled=True,
                platform=Platform.TELEGRAM,
                user_id="admin-user",
                chat_id="admin-chat",
            )
        )

        result = await runner._handle_yolo_command(
            _event("/yolo", user_id="requester", chat_id="requester-chat")
        )

        assert "disabled while admin approval routing is enabled" in str(result)
