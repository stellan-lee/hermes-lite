# Administrator Action Intents

## Intent declaration

### Why

Administrator approval is currently routed through the dangerous-command
queue. A model can also request approval for an arbitrary action, but that is
advisory: the approval result is not bound to the later tool invocation. This
makes database mutations, device commands, and plugin-provided side effects
look like shell-command approvals and leaves enforcement to model behavior.

### What

Move the administrator boundary to central tool dispatch. A tool may register
an action-intent builder. When exact-admin routing is active, Marlow builds a
typed intent from the already-coerced tool arguments, asks the administrator,
and executes the same call only after a one-shot approval. Decline, timeout,
delivery failure, or malformed intent fail closed.

MCP tools that explicitly advertise `destructiveHint: true` or
`readOnlyHint: false` are treated as action-intent tools automatically. Tools
without explicit mutation metadata keep their existing behavior.

### How

- Add an immutable `ActionIntent` value with semantic type, operation, target,
  impact, review parameters, tool identity, and a digest of the exact original
  arguments.
- Add optional `action_intent` metadata to the central registry and plugin
  registration facade.
- Enforce registered action intents in `handle_function_call()` after plugin
  pre-call blocks and before handler dispatch.
- Keep approval and execution in the same synchronous dispatch stack so a
  model cannot swap arguments after approval.
- Preserve legacy adapter contracts internally, but render administrator
  prompts as action approvals and attach structured intent data to hooks.
- Keep the model-callable `request_admin_approval` tool as a compatibility
  escape hatch for actions outside registered tools.

## Security properties

- Approval is request-scoped and exact-admin only.
- The argument digest is computed from unredacted canonical arguments; display
  parameters are redacted before leaving the process.
- A malformed intent builder blocks the tool rather than silently skipping
  approval.
- Read-only or unannotated MCP tools are not guessed to be mutating.
- Existing hardline terminal blocks remain non-approvable.

## Non-goals

- Broad grants such as "manipulate the database" are not introduced.
- Tool descriptions are not used to guess whether a tool mutates state.
- Existing originating-user command approvals are not changed when exact-admin
  routing is disabled.
