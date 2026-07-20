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

## [FEAT-20260720-001] telegram-work-experience-recall

**Logged**: 2026-07-20T08:55:02+08:00
**Priority**: medium
**Status**: resolved
**Area**: backend

### Requested Capability

Support Work Experience recall for turns received through Telegram.

### User Context

The profile owner wants Telegram tasks to benefit from the same approved,
project-scoped lessons available in the classic CLI.

### Complexity Estimate

medium

### Suggested Implementation

Add an explicit Telegram turn origin, preserve the untouched inbound request,
bind direct-message recall to one configured owner user ID, and retain all
existing project and provider-egress checks.

### Metadata

- Frequency: first_time
- Related Features: Work Experience, Telegram gateway, provider egress

### Resolution

- **Resolved**: 2026-07-20T09:22:00+08:00
- **Notes**: Added owner-bound Telegram DM recall with raw-input separation,
  retained project/provider authorization, documented configuration, and
  completed the full gateway and focused Work Experience test suites.

---
