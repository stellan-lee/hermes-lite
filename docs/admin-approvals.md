# Administrator-routed approvals

Hermes can pause a gateway session and route privileged-action decisions to
one configured administrator, including an administrator on another connected
messaging platform. The originating agent resumes only after that specific
request is approved or declined.

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

Supported interactive adapters are Telegram, Discord, Slack, Feishu, Matrix,
Microsoft Teams, and QQBot. The configured platform must be connected when a
request is sent.

## Behavior

- Dangerous terminal commands and gateway `execute_code` requests are routed
  automatically.
- The model can call `request_admin_approval` for a privileged action that is
  not already covered by a tool safety prompt.
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
