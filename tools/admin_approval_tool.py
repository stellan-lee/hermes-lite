"""Agent-callable administrator approval tool.

This tool is intentionally a thin wrapper around ``tools.approval``. The
approval core owns the blocking queue, while the gateway callback owns secure
routing to the configured administrator and resumes the originating session.
"""

import json

from tools.approval import request_admin_approval
from tools.registry import registry


def admin_approval_tool(
    action: str,
    reason: str = "",
    *,
    action_type: str = "custom.action",
    operation: str = "",
    target: str = "",
    impact: str = "",
    parameters=None,
) -> str:
    """Block until the configured gateway administrator decides."""
    return json.dumps(
        request_admin_approval(
            action=action,
            reason=reason,
            action_type=action_type,
            operation=operation,
            target=target,
            impact=impact,
            parameters=parameters,
        ),
        ensure_ascii=False,
    )


ADMIN_APPROVAL_SCHEMA = {
    "name": "request_admin_approval",
    "description": (
        "Ask the configured gateway administrator to approve or decline a "
        "specific semantic action intent, then wait for the decision. Use "
        "this only for external actions that are not already protected by a "
        "registered tool action-intent policy. Describe what will change, "
        "where, and its impact instead of supplying an implementation shell "
        "command. Approval is one-shot. Never act when approved=false."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "Concrete action awaiting authorization, including the "
                    "target and material effect."
                ),
            },
            "reason": {
                "type": "string",
                "description": (
                    "Why the action is needed and the relevant risk or impact."
                ),
            },
            "action_type": {
                "type": "string",
                "description": (
                    "Stable semantic category, such as database.update or "
                    "device.command."
                ),
            },
            "operation": {
                "type": "string",
                "description": "The operation to perform, such as update or unlock.",
            },
            "target": {
                "type": "string",
                "description": "The exact database, record set, device, or resource.",
            },
            "impact": {
                "type": "string",
                "description": "The material external effect if the action succeeds.",
            },
            "parameters": {
                "type": "object",
                "description": (
                    "Non-secret parameters needed to distinguish the exact action."
                ),
                "additionalProperties": True,
            },
        },
        "required": ["action"],
    },
}


registry.register(
    name="request_admin_approval",
    toolset="admin_approval",
    schema=ADMIN_APPROVAL_SCHEMA,
    handler=lambda args, **_kw: admin_approval_tool(
        action=args.get("action", ""),
        reason=args.get("reason", ""),
        action_type=args.get("action_type", "custom.action"),
        operation=args.get("operation", ""),
        target=args.get("target", ""),
        impact=args.get("impact", ""),
        parameters=args.get("parameters"),
    ),
    check_fn=lambda: True,
    emoji="🛡️",
)
