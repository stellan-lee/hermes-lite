# Administrator-routed approvals

Marlow can pause a gateway session and route structured action-intent decisions
to one configured administrator, including an administrator on another
connected messaging platform. The originating agent resumes only after that
specific request is approved or declined.

## Configuration

Configure the administrator's stable platform user ID locally. The identity
cannot be bootstrapped from a chat command.

```yaml
approvals:
  admin:
    enabled: true
    platform: telegram
    user_id: "123456789"
    chat_id: "123456789"
    thread_id: null
```

`user_id` is the authorization boundary. `chat_id` and optional `thread_id`
are only delivery destinations. After `platform` and `user_id` are configured
locally and the gateway has restarted, that administrator can run
`/set_admin_channel` in the desired chat or thread to update the destination
without changing the trusted identity. `/whoami` shows the platform identity
values needed for the local configuration.

Supported interactive adapters are Telegram, Discord, Slack, and Feishu. The
configured platform must be connected when a request is sent.

## Behavior

- Dangerous terminal commands and gateway `execute_code` requests are wrapped
  as `terminal.execute` and `code.execute` action intents automatically.
- Any built-in or plugin tool registered with `action_intent` is intercepted at
  central dispatch. Approval and execution happen in one call stack, so the
  approved arguments cannot be replaced before the handler runs.
- MCP tools that explicitly declare `destructiveHint: true` or
  `readOnlyHint: false` are registered as `mcp.mutation` action intents.
- The model can call `request_admin_approval` for a privileged action that is
  not represented by a registered tool. This is a compatibility escape hatch;
  registered action-intent policies are preferred because they bind approval
  directly to execution.
- Each card has only **Approve** and **Decline**. Approval is one-shot and tied
  to the request ID; it never creates a session or permanent grant.
- Only the configured user can operate the card, even when a platform's normal
  allowlist is broader.
- Delivery failure, timeout, stale cards, invalid identities, and incomplete
  configuration all fail closed.
- `/approve`, `/deny`, and `/yolo` cannot bypass administrator routing while it
  is enabled. Administrator routing also takes precedence over `mode: off`,
  smart auto-approval, prior command grants, and process/session YOLO settings
  for gateway approvals.

When `approvals.admin.enabled` is false, the existing originating-chat approval
behavior is unchanged.

## Registering a side-effecting tool

Tools declare semantic intent rather than implementation commands. A builder
receives a private copy of the exact, schema-coerced arguments. Returning
`None` identifies a read-only branch of a mixed-purpose tool.

```python
ctx.register_tool(
    name="set_device_state",
    toolset="devices",
    schema=DEVICE_SCHEMA,
    handler=set_device_state,
    action_intent=lambda args: {
        "action_type": "device.command",
        "operation": args["state"],
        "target": f"device:{args['device_id']}",
        "reason": "The user requested a physical device state change.",
        "impact": f"Device will enter state {args['state']!r}.",
        "parameters": {
            "device_id": args["device_id"],
            "state": args["state"],
        },
    },
)
```

A database tool can branch on its operation:

```python
def database_intent(args):
    if args["operation"] == "select":
        return None
    return {
        "action_type": f"database.{args['operation']}",
        "operation": args["operation"],
        "target": args["table"],
        "impact": "Rows in the production database may change.",
        "parameters": {
            "table": args["table"],
            "where": args.get("where"),
            "changes": args.get("changes"),
        },
    }
```

The approval card renders the semantic intent as labeled text plus a SHA-256
digest bound to the original tool name and unredacted arguments. The structured
intent remains attached to approval hooks, while display parameters are
secret-redacted before being sent to the messaging adapter.
