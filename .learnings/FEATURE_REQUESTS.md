# Feature Requests

## [FEAT-20260719-001] execution-bound-admin-action-intents

**Logged**: 2026-07-19T00:00:00+08:00
**Priority**: high
**Status**: resolved
**Area**: backend

### Requested Capability

Administrator approval should authorize semantic actions such as database
mutations or device commands, rather than only high-risk shell commands.

### User Context

The administrator needs to review the intended external effect and target
before an agent changes a database or controls a device. Command-only prompts
expose implementation details and do not cover non-terminal tools.

### Complexity Estimate

complex

### Suggested Implementation

Add structured action-intent metadata to tool registration, enforce it in
central dispatch, bind each one-shot approval to the exact tool arguments, and
map explicit MCP mutation annotations into the same policy.

### Metadata

- Frequency: first_time
- Related Features: administrator-routed approvals, tool registry, MCP tools

### Resolution

- **Resolved**: 2026-07-19T00:00:00+08:00
- **Notes**: Added central execution-bound action intents, plugin registry
  metadata, MCP mutation annotation mapping, semantic admin cards, and focused
  fail-closed tests.

---
