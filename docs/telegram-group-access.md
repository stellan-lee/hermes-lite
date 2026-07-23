# Telegram group access management

Telegram group administrators can grant users access to Marlow directly from
the group. Runtime grants avoid editing `config.yaml` or `.env` and take effect
without restarting the gateway.

## Prerequisites

- The Marlow bot must be a Telegram group administrator. Telegram only
  guarantees that bots can verify other members' administrator status in that
  configuration.
- The caller must be a Telegram administrator or owner of the current group.

## Commands

Reply to a member's message:

```text
/access grant
/access revoke
```

Numeric Telegram user IDs are also supported:

```text
/access grant 123456789
/access revoke 123456789
/access list
```

Telegram usernames are not accepted because bots cannot reliably resolve an
arbitrary mutable `@username` to a user ID.

## Behavior and security

- A grant applies only to the exact group where the command was issued. It
  does not authorize the user in another group or in direct messages.
- Grants apply immediately and survive gateway restarts.
- The replied-to message is not processed retroactively. Future messages can
  reach Marlow and must still follow normal trigger rules such as
  `require_mention`.
- Runtime grants do not override explicit Telegram chat or topic response
  gates such as `allowed_chats` and `allowed_topics`.
- Existing `group_allow_from`, `group_allowed_chats`, and environment
  allowlists continue to work. `/access revoke` removes only a runtime grant;
  it cannot override access granted by configuration.
- Slash-command permissions remain controlled separately by
  `group_allow_admin_from` and `group_user_allowed_commands`.
- If Telegram administrator verification fails, the command is denied.

Runtime grants are stored in the active profile under
`platforms/telegram/group-access.json` using atomic writes and owner-only file
permissions.
