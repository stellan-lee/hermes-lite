"""Agent-callable administrator approval tool.

This tool is intentionally a thin wrapper around ``tools.approval``. The
approval core owns the blocking queue, while the gateway callback owns secure
routing to the configured administrator and resumes the originating session.
"""

import json

from tools.approval import request_admin_approval
from tools.registry import registry


def admin_approval_tool(action: str, reason: str = "") -> str:
    """Block until the configured gateway administrator decides."""
    return json.dumps(
        request_admin_approval(action=action, reason=reason),
        ensure_ascii=False,
    )


ADMIN_APPROVAL_SCHEMA = {
    "name": "request_admin_approval",
    "description": (
        "Ask the configured gateway administrator to approve or decline a "
        "specific privileged action, then wait for the decision. Use this "
        "before actions that require administrator authorization but are not "
        "already covered by an automatic tool safety prompt. Approval is "
        "one-shot and applies only to the action exactly described. Never "
        "perform the action when the result says approved=false."
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
    ),
    check_fn=lambda: True,
    emoji="🛡️",
)
