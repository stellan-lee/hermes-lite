# Telegram guest digital twin

Marlow can serve every authorized Telegram source outside the exact configured
super-admin conversation as a guest-facing digital twin of the profile owner.
Guest turns combine a global role prompt, the existing per-chat or per-topic
prompt, and scoped Work Experience recall.

This feature changes context, not authorization. It does not widen Telegram
allowlists or mention gates, grant admin permissions, expose personal memory,
or let guests capture or govern Work Experience.

## Configure the admin boundary

Configure the trusted administrator and destination locally:

```yaml
approvals:
  admin:
    enabled: true
    conversation_mode: super_admin
    platform: telegram
    user_id: "123456789"
    chat_id: "123456789"
    thread_id: null
```

Configure this block locally and restart the gateway. `user_id` remains the
privileged authorization boundary. The exact configured user, chat, and
optional thread form the super-admin conversation excluded from guest mode.

When `thread_id` is set, that administrator is elevated only in that topic.
When it is unset, the administrator is elevated throughout the configured
chat. Other users in the same chat remain guests.

## Enable the digital twin

```yaml
experience:
  mode: assist
  telegram_digital_twin:
    enabled: true
    system_prompt: >-
      Represent the profile owner's established working style for guests.
      Be concise, practical, and transparent that you are an AI assistant.

telegram:
  channel_prompts:
    "-1001234567890": "Focus on release engineering for this group."
    "42": "Focus on customer support for this topic."
```

The prompt order is:

1. Normal Marlow and Telegram context.
2. `experience.telegram_digital_twin.system_prompt`.
3. The matching `telegram.channel_prompts` entry.
4. The gateway's existing global ephemeral system prompt, when configured.

The channel prompt specializes the global guest role. Prompt text cannot
override tool policies, identity checks, approval routing, or Work Experience
governance.

## Work Experience behavior

Every dispatched Telegram turn that is not the exact super-admin source becomes
eligible for the same bounded, relevance-based Work Experience retrieval used
by the local owner. Recall still requires:

- global `experience.mode` set to `shadow` or `assist`;
- an explicit project policy allowing recall;
- injection consent for `assist` mode;
- matching repository and project scope;
- an allowed provider-egress policy; and
- active, approved lessons that meet the confidence threshold.

Guest turns never capture experience. Marlow does not inject the profile
owner's personal memory, private conversation history, or the complete
experience database. The personal-memory and cross-session-search toolsets are
also removed from guest agents.

## Rollback

Set `experience.telegram_digital_twin.enabled: false`. Existing Telegram
message routing, the super-admin conversation, per-channel prompts, and
owner-bound DM recall remain unchanged.
