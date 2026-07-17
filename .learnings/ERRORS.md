# Errors

## [ERR-20260717-001] repository-workflow-discovery

**Logged**: 2026-07-17T00:00:00+08:00
**Priority**: medium
**Status**: wont_fix
**Area**: docs

### Summary

The supplied repository instructions reference three workflow rule files that
are not present in the checkout.

### Error

```
wc: rules/workflow.md: open: No such file or directory
wc: rules/agent-usage.md: open: No such file or directory
wc: rules/task-tracking.md: open: No such file or directory
```

### Context

- Attempted to read every rule referenced by the task's AGENTS.md instructions.
- The checked-in `AGENTS.md` does not contain those references and no matching
  files were found under the worktree.

### Suggested fix

Either add the referenced rule files to the repository or remove the stale
references from the external project instructions.

### Metadata

- Reproducible: yes
- Related Files: AGENTS.md

### Resolution

- **Resolved**: 2026-07-17T00:00:00+08:00
- **Notes**: The checked-in development guide is now self-contained. The stale
  references came from external task instructions and are not editable in this
  repository.

---

## [ERR-20260717-005] diff-whitespace-audit

**Logged**: 2026-07-17T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary

The first complete diff check found redundant blank lines at end of file.

### Error

```
new blank line at EOF
```

### Context

- Ten newly replaced text files contained more than one trailing newline.
- Ruff does not report this Git whitespace condition.

### Suggested fix

Normalize changed text files to exactly one trailing newline and rerun
`git diff --check HEAD` independently.

### Metadata

- Reproducible: yes
- Related Files: README.md, AGENTS.md, pyproject.toml, configuration examples

### Resolution

- **Resolved**: 2026-07-17T00:00:00+08:00
- **Notes**: All text files were normalized and independent diff checks pass.

---

## [ERR-20260717-003] agent-request-snapshot

**Logged**: 2026-07-17T00:00:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: backend

### Summary

Model requests referenced the live conversation list and changed after the
request returned.

### Error

```
2 failed, 35 passed
Recorded request messages ended with later assistant messages instead of the
user/tool message present when create() was called.
```

### Context

- The agent appended new messages to the same list passed to the model client.
- A synchronous real client serializes immediately, but mocks or alternate
  clients can retain the object and observe later mutations.

### Suggested fix

Pass a deep snapshot of messages for each model request.

### Metadata

- Reproducible: yes
- Related Files: run_agent.py, tests/test_agent.py

### Resolution

- **Resolved**: 2026-07-17T00:00:00+08:00
- **Notes**: Each request now receives `copy.deepcopy(messages)`.

---

## [ERR-20260717-004] initial-ruff-check

**Logged**: 2026-07-17T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary

The first Ruff pass reported import ordering, line length, annotation, and test
style issues in the new minimal source.

### Error

```
Found 13 errors.
```

### Context

- First static check after replacing the legacy repository.
- Nine findings are mechanically fixable; four require small formatting edits.

### Suggested fix

Apply Ruff's safe fixes, format the remaining long lines, and rerun from clean
output.

### Metadata

- Reproducible: yes
- Related Files: cli.py, hermes_constants.py, hermes_state.py, tests/, tools/

### Resolution

- **Resolved**: 2026-07-17T00:00:00+08:00
- **Notes**: Applied safe automatic fixes and formatted the four remaining findings.
  A later security-test expansion introduced one import-order recurrence; it
  was fixed immediately and included in the next complete lint run.

---

## [ERR-20260717-002] validation-python-command

**Logged**: 2026-07-17T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary

The clean worktree has `python3` but no `python` executable.

### Error

```
zsh:1: command not found: python
```

### Context

- The validation probe and initial test-wrapper fallback used `python`.
- No project virtual environment exists in this worktree yet.

### Suggested fix

Use `python3` as the final no-virtualenv fallback.

### Metadata

- Reproducible: yes
- Related Files: scripts/run_tests.sh

### Resolution

- **Resolved**: 2026-07-17T00:00:00+08:00
- **Notes**: The wrapper now falls back to `python3`.

---
