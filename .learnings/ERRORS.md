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

## [ERR-20260718-001] scoped-codex-import-check

**Logged**: 2026-07-18T06:35:56+08:00
**Priority**: low
**Status**: resolved
**Area**: backend

### Summary

The first scoped Codex restoration omitted one shared fallback identity.

### Error

```
ModuleNotFoundError: No module named 'agent.prompt_builder'
```

### Context

- Restored only the dedicated Codex modules from the pre-cleanup revision.
- `agent.codex_responses_adapter` imports `DEFAULT_AGENT_IDENTITY` from the
  former shared prompt builder.

### Suggested fix

Restore only the exact fallback identity used by Codex rather than the full
prompt builder and its skills, memory, and context-loading dependency chain.

### Metadata

- Reproducible: yes
- Related Files: agent/codex_responses_adapter.py, agent/prompt_builder.py

### Resolution

- **Resolved**: 2026-07-18T06:35:56+08:00
- **Notes**: Restored the original fallback identity as the sole retained
  prompt-builder surface; every selected Codex module now imports cleanly.

---

## [ERR-20260718-002] host-python-missing-pytest

**Logged**: 2026-07-18T06:35:56+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary

The host Python installation does not include the project's test dependency.

### Error

```
/opt/homebrew/opt/python@3.14/bin/python3.14: No module named pytest
```

### Context

- Attempted to run the focused restored Codex tests with `python3 -m pytest`.
- The project virtual environment had been removed after the previous clean
  package validation.

### Suggested fix

Run validation through `uv` with the declared development extra so dependencies
come from the project lock rather than the host interpreter.

### Resolution

- **Resolved**: 2026-07-18T08:00:00+08:00
- **Notes**: `uv run --extra dev` provisioned the declared test environment;
  the complete suite passes on Python 3.11 and 3.14.

---

## [ERR-20260718-003] scoped-codex-test-collection

**Logged**: 2026-07-18T08:00:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: tests

### Summary

The first historical Codex test restoration included package markers and mixed
xAI/GitHub/provider cases that were outside the selective revert.

### Error

```
ModuleNotFoundError caused by the tests/agent package shadowing agent/
ModuleNotFoundError: No module named 'agent.model_metadata'
```

### Context

- Restored Codex-named test files from the pre-cleanup revision.
- Some files also tested unrelated Responses providers and old CLI/provider
  integration modules that intentionally remain deleted.

### Resolution

- **Resolved**: 2026-07-18T08:00:00+08:00
- **Notes**: Restored the package markers and retained only Codex-specific test
  cases. No xAI, GitHub Models, or generic provider stack was restored.

---

## [ERR-20260718-004] restored-codex-lint-drift

**Logged**: 2026-07-18T08:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: backend

### Summary

The pre-cleanup Codex sources did not satisfy Hermes Lite's stricter Ruff rules.

### Error

```
Found 203 errors.
```

### Context

Most findings were mechanical typing syntax, import ordering, line wrapping,
or simplification rules in restored files.

### Resolution

- **Resolved**: 2026-07-18T08:00:00+08:00
- **Notes**: Applied Ruff's safe fixes and formatting, then reviewed and fixed
  every remaining diagnostic. The full lint command passes.

---

## [ERR-20260718-005] patch-context-mismatch

**Logged**: 2026-07-18T08:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary

A multi-file documentation patch used an incorrect line wrap and was rejected
atomically.

### Error

```
apply_patch verification failed: Failed to find expected lines in
.plans/hermes-lite-cleanup.md
```

### Resolution

- **Resolved**: 2026-07-18T08:00:00+08:00
- **Notes**: Re-read the exact context and applied the corrected documentation
  patch; no partial edit had occurred.

---

## [ERR-20260718-006] wheel-audit-cleanup-policy

**Logged**: 2026-07-18T08:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: infra

### Summary

The first isolated-wheel audit was rejected before execution because its shell
trap contained `rm -rf` for a temporary directory.

### Error

```
Rejected: rm -f style commands are not permitted
```

### Resolution

- **Resolved**: 2026-07-18T08:00:00+08:00
- **Notes**: Re-ran the audit in a uniquely named `/tmp` directory without an
  inline destructive cleanup. Wheel imports, both entry points, the fixed
  provider registry, and Codex binary detection passed.

### Metadata

- Reproducible: yes
- Related Files: pyproject.toml, uv.lock

---
