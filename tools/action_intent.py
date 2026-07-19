"""Typed, execution-bound action intents for administrator approval.

An action intent describes *what* a tool invocation will do without reducing
the decision to a shell command. The digest is computed from the exact,
unredacted tool arguments. Parameters shown to an administrator are separately
redacted so credentials are not copied into messaging platforms.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, cast


ActionIntentBuilder = Callable[[dict[str, Any]], Mapping[str, Any] | None]


def _canonical_json(value: Any) -> str:
    """Return stable JSON for hashing, tolerating defensive non-JSON values."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: repr(item),
    )


def _redact_parameters(value: Any) -> Any:
    """Return a JSON-safe, secret-redacted copy for administrator display."""
    serialized = _canonical_json(value)
    try:
        from agent.redact import redact_sensitive_text

        serialized = redact_sensitive_text(serialized, force=True)
    except Exception:
        # Do not leak raw arguments merely because the redaction layer failed.
        # The unredacted digest still binds approval to the exact invocation.
        return {"summary": "Parameters omitted because secret redaction was unavailable."}
    try:
        return json.loads(serialized)
    except (TypeError, ValueError):
        return {"summary": serialized}


def argument_digest(tool_name: str, args: Mapping[str, Any]) -> str:
    """Bind an intent to one exact tool name and argument object."""
    material = _canonical_json({"tool": tool_name, "arguments": args})
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ActionIntent:
    """Semantic description of a single side-effecting tool invocation."""

    action_type: str
    operation: str
    target: str
    reason: str
    impact: str
    parameters: Any
    tool_name: str
    argument_digest: str
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "action_type": self.action_type,
            "operation": self.operation,
            "target": self.target,
            "reason": self.reason,
            "impact": self.impact,
            "parameters": copy.deepcopy(self.parameters),
            "tool_name": self.tool_name,
            "argument_digest": self.argument_digest,
        }

    def summary(self) -> str:
        """Render reviewable semantic action data for existing adapters."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def build_action_intent(
    *,
    tool_name: str,
    args: Mapping[str, Any],
    builder: ActionIntentBuilder | Mapping[str, Any],
) -> ActionIntent | None:
    """Build and validate an intent from registry metadata.

    A callable may return ``None`` for a read-only branch of a mixed-purpose
    tool. Any other malformed value raises and therefore fails closed at the
    dispatch boundary.
    """
    exact_args = copy.deepcopy(dict(args))
    if isinstance(builder, Mapping):
        spec = builder
    else:
        spec = builder(copy.deepcopy(exact_args))
    if spec is None:
        return None
    if not isinstance(spec, Mapping):
        raise TypeError("action_intent builder must return a mapping or None")
    spec = cast(Mapping[str, Any], spec)

    action_type = str(spec.get("action_type") or "tool.action").strip()
    operation = str(spec.get("operation") or tool_name).strip()
    target = str(spec.get("target") or tool_name).strip()
    reason = str(spec.get("reason") or "Administrator authorization is required.").strip()
    impact = str(spec.get("impact") or "This action may change external state.").strip()
    if not action_type or not operation or not target:
        raise ValueError("action_type, operation, and target must be non-empty")

    review_parameters = spec.get("parameters", exact_args)
    return ActionIntent(
        action_type=action_type,
        operation=operation,
        target=target,
        reason=reason,
        impact=impact,
        parameters=_redact_parameters(review_parameters),
        tool_name=tool_name,
        argument_digest=argument_digest(tool_name, exact_args),
    )


def build_manual_action_intent(
    action: str,
    reason: str = "",
    *,
    action_type: str = "custom.action",
    operation: str = "",
    target: str = "",
    impact: str = "",
    parameters: Any = None,
) -> ActionIntent:
    """Build a compatibility intent for the model-callable approval tool."""
    action = str(action or "").strip()
    if not action:
        raise ValueError("An action description is required.")
    manual_args = {
        "action": action,
        "reason": reason,
        "action_type": action_type,
        "operation": operation,
        "target": target,
        "impact": impact,
        "parameters": parameters,
    }
    return ActionIntent(
        action_type=str(action_type or "custom.action").strip(),
        operation=str(operation or action).strip(),
        target=str(target or "administrator-managed resource").strip(),
        reason=str(reason or "Administrator authorization is required.").strip(),
        impact=str(impact or action).strip(),
        parameters=_redact_parameters(parameters if parameters is not None else {}),
        tool_name="request_admin_approval",
        argument_digest=argument_digest("request_admin_approval", manual_args),
    )
