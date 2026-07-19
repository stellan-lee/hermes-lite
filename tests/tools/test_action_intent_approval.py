"""Execution-bound administrator action-intent tests."""

import json

from model_tools import handle_function_call
from tools.action_intent import build_action_intent
from tools.registry import registry


def _schema(name):
    return {
        "name": name,
        "description": "Test action intent tool",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string"},
                "state": {"type": "string"},
            },
        },
    }


def _device_intent(args):
    return {
        "action_type": "device.command",
        "operation": args["state"],
        "target": f"device:{args['device_id']}",
        "reason": "A physical device state change was requested.",
        "impact": f"The device will enter state {args['state']}.",
        "parameters": args,
    }


def test_action_intent_binds_exact_arguments_and_redacts_secrets():
    intent = build_action_intent(
        tool_name="database_mutate",
        args={"table": "devices", "password": "very-secret-password"},
        builder={
            "action_type": "database.update",
            "operation": "update",
            "target": "production.devices",
        },
    )
    changed = build_action_intent(
        tool_name="database_mutate",
        args={"table": "users", "password": "very-secret-password"},
        builder={
            "action_type": "database.update",
            "operation": "update",
            "target": "production.devices",
        },
    )

    assert intent.argument_digest != changed.argument_digest
    assert "very-secret-password" not in intent.summary()
    assert intent.parameters["table"] == "devices"


def test_registered_action_is_approved_before_the_same_arguments_execute(monkeypatch):
    name = "test_device_action_intent_approved"
    executed = []
    reviewed = []

    registry.register(
        name=name,
        toolset="test-action-intents",
        schema=_schema(name),
        handler=lambda args, **_kwargs: executed.append(dict(args)) or json.dumps({"ok": True}),
        action_intent=_device_intent,
    )
    monkeypatch.setattr(
        "tools.approval.is_admin_action_approval_enabled", lambda: True
    )

    def approve(intent):
        reviewed.append(intent)
        return {"approved": True, "decision": "approved", "request_id": "req-1"}

    monkeypatch.setattr("tools.approval.request_action_intent_approval", approve)
    try:
        result = json.loads(
            handle_function_call(
                name,
                {"device_id": "lock-7", "state": "unlock"},
                skip_pre_tool_call_hook=True,
            )
        )
    finally:
        registry.deregister(name)

    assert result == {"ok": True}
    assert executed == [{"device_id": "lock-7", "state": "unlock"}]
    assert reviewed[0].action_type == "device.command"
    assert reviewed[0].operation == "unlock"
    assert reviewed[0].target == "device:lock-7"


def test_declined_action_never_reaches_handler(monkeypatch):
    name = "test_database_action_intent_declined"
    executed = []
    registry.register(
        name=name,
        toolset="test-action-intents",
        schema=_schema(name),
        handler=lambda args, **_kwargs: executed.append(args) or "{}",
        action_intent={
            "action_type": "database.update",
            "operation": "update",
            "target": "production.devices",
        },
    )
    monkeypatch.setattr(
        "tools.approval.is_admin_action_approval_enabled", lambda: True
    )
    monkeypatch.setattr(
        "tools.approval.request_action_intent_approval",
        lambda _intent: {
            "approved": False,
            "decision": "declined",
            "request_id": "req-2",
            "message": "The administrator declined the database update.",
        },
    )
    try:
        result = json.loads(
            handle_function_call(
                name,
                {"device_id": "42", "state": "disabled"},
                skip_pre_tool_call_hook=True,
            )
        )
    finally:
        registry.deregister(name)

    assert executed == []
    assert result["approved"] is False
    assert result["status"] == "blocked"
    assert result["decision"] == "declined"
    assert result["request_id"] == "req-2"


def test_timed_out_action_never_reaches_handler(monkeypatch):
    name = "test_device_action_intent_timeout"
    executed = []
    registry.register(
        name=name,
        toolset="test-action-intents",
        schema=_schema(name),
        handler=lambda args, **_kwargs: executed.append(args) or "{}",
        action_intent=_device_intent,
    )
    monkeypatch.setattr(
        "tools.approval.is_admin_action_approval_enabled", lambda: True
    )
    monkeypatch.setattr(
        "tools.approval.request_action_intent_approval",
        lambda _intent: {
            "approved": False,
            "decision": "timeout",
            "request_id": "req-timeout",
            "message": "Admin approval timed out.",
        },
    )
    try:
        result = json.loads(
            handle_function_call(
                name,
                {"device_id": "lock-7", "state": "unlock"},
                skip_pre_tool_call_hook=True,
            )
        )
    finally:
        registry.deregister(name)

    assert executed == []
    assert result["approved"] is False
    assert result["decision"] == "timeout"
    assert result["request_id"] == "req-timeout"


def test_invalid_intent_builder_fails_closed(monkeypatch):
    name = "test_invalid_action_intent"
    executed = []
    registry.register(
        name=name,
        toolset="test-action-intents",
        schema=_schema(name),
        handler=lambda args, **_kwargs: executed.append(args) or "{}",
        action_intent=lambda _args: "not-a-mapping",
    )
    monkeypatch.setattr(
        "tools.approval.is_admin_action_approval_enabled", lambda: True
    )
    try:
        result = json.loads(
            handle_function_call(name, {}, skip_pre_tool_call_hook=True)
        )
    finally:
        registry.deregister(name)

    assert executed == []
    assert result["approved"] is False
    assert result["decision"] == "invalid_intent"


def test_read_only_branch_and_disabled_admin_do_not_prompt(monkeypatch):
    name = "test_mixed_action_intent"
    executed = []
    prompted = []
    registry.register(
        name=name,
        toolset="test-action-intents",
        schema=_schema(name),
        handler=lambda args, **_kwargs: executed.append(dict(args)) or json.dumps({"ok": True}),
        action_intent=lambda args: None if args.get("state") == "read" else _device_intent(args),
    )
    monkeypatch.setattr(
        "tools.approval.request_action_intent_approval",
        lambda intent: prompted.append(intent) or {"approved": True},
    )
    try:
        monkeypatch.setattr(
            "tools.approval.is_admin_action_approval_enabled", lambda: True
        )
        read_result = json.loads(
            handle_function_call(
                name,
                {"device_id": "sensor-1", "state": "read"},
                skip_pre_tool_call_hook=True,
            )
        )

        monkeypatch.setattr(
            "tools.approval.is_admin_action_approval_enabled", lambda: False
        )
        disabled_result = json.loads(
            handle_function_call(
                name,
                {"device_id": "sensor-1", "state": "reset"},
                skip_pre_tool_call_hook=True,
            )
        )
    finally:
        registry.deregister(name)

    assert read_result == {"ok": True}
    assert disabled_result == {"ok": True}
    assert prompted == []
    assert len(executed) == 2
