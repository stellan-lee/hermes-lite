# Errors

## [ERR-20260718-020] broad-legacy-config-patch-context

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tooling

### Summary

A combined provider-alias and environment-sanitizer removal patch missed because the sanitizer's current implementation included extra null-byte handling beyond the inspected excerpt.

### Error

```
apply_patch verification failed: Failed to find expected _sanitize_env_lines block
```

### Resolution

Split provider normalizer edits from sanitizer removal and inspected exact function boundaries before retrying.

### Metadata

- Reproducible: no
- Related Files: hermes_cli/config.py, hermes_cli/env_loader.py

---

## [ERR-20260718-019] telegram-provider-group-orphan-block

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: implementation

### Summary

Removing the Telegram provider-group callback branch left its trailing keyboard-render block indented inside the preceding successful model-switch branch.

### Error

Static compilation passed, but review found references to deleted variables (`buttons`, `_label`, `group_id`) on the successful model-switch path.

### Resolution

Removed the complete orphaned group-keyboard fragment and recompiled the adapter.

### Metadata

- Reproducible: yes
- Related Files: gateway/platforms/telegram.py

---

## [ERR-20260718-018] platform-audit-shell-quoting

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tooling

### Summary

A combined ripgrep regex used nested shell quotes that zsh interpreted as a glob, so the read-only platform audit did not run.

### Error

```
zsh: bad pattern
```

### Resolution

Replaced the combined shell regex with multiple explicitly quoted ripgrep patterns.

### Metadata

- Reproducible: no
- Related Files: none

---

## [ERR-20260718-017] doctor-platform-guard-indentation

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: implementation

### Summary

Removing the doctor command-installation platform guard left its body over-indented and caused an `IndentationError` during compilation.

### Error

```
IndentationError: unexpected indent (doctor.py, line 723)
```

### Resolution

Replaced the removed native-Windows exclusion with an explicit POSIX scope matching the supported macOS/Linux targets, preserving the existing block structure.

### Metadata

- Reproducible: no
- Related Files: hermes_cli/doctor.py

---

## [ERR-20260718-016] cli-windows-regex-patch-escaping

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tooling

### Summary

A combined CLI cleanup patch failed because the expected Python regex string did not preserve the file's exact backslash escaping.

### Error

```
apply_patch verification failed: Failed to find expected Windows path regex block
```

### Resolution

Inspected the exact source and reapplied the regex removal separately from comment-only edits.

### Metadata

- Reproducible: no
- Related Files: cli.py

---

## [ERR-20260718-015] gateway-status-platform-patch-context

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tooling

### Summary

A multi-section gateway status patch failed on one stale comment context.

### Error

```
apply_patch verification failed: Failed to find expected Windows normalization lines
```

### Resolution

Applied the import, lock, PID, and comment changes as independent patches and recompiled the module.

### Metadata

- Reproducible: no
- Related Files: gateway/status.py

---

## [ERR-20260718-014] oversized-main-cleanup-patch-context

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tooling

### Summary

An oversized patch for Termux startup removal failed because its copied context omitted intervening comments.

### Error

```
apply_patch verification failed: Failed to find expected lines in hermes_cli/main.py
```

### Context

- The patch attempted to remove several distant helper groups in one operation.
- The source contained additional explanatory comments not included in the patch context.

### Resolution

Split the edit into smaller function-level patches and applied them successfully.

### Metadata

- Reproducible: no
- Related Files: hermes_cli/main.py

---

## [ERR-20260718-013] removed-termux-mode-affected-tui-height-test

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary

A virtual-height test only distinguished prompt widths under the removed Termux sizing mode.

### Error

```
expected estimatedMsgHeight(..., 26, '❯') to be 3, received 4
```

### Context

- The production TUI still had a Termux-only sizing branch even though Android/Termux support is selected for removal.
- The test's narrow dimensions were clamped to the same desktop minimum width for both prompts.

### Suggested Fix

Remove the checked Termux-specific layout mode and exercise compound prompt sizing above the desktop minimum width.

### Metadata

- Reproducible: yes
- Related Files: ui-tui/src/config/env.ts, ui-tui/src/lib/virtualHeights.ts

### Resolution

Removed Termux-only layout handling and updated the width test to exercise the retained desktop sizing contract. All 913 TUI tests now pass (one skipped).

---

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

## [ERR-20260718-012] tui-test-preconditions

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary

TUI tests were launched before building `@hermes/ink` and inherited SSH markers.

### Error

```
Cannot find module './dist/entry-exports.js'
Cursor terminal setup must be run on the local machine, not inside an SSH session.
```

### Context

- The TUI test suite imports the built local Ink workspace.
- Terminal-setup tests deliberately reject environments with `SSH_CONNECTION`.

### Suggested Fix

Build `@hermes/ink` first and remove ambient SSH markers only for the test process.

### Metadata

- Reproducible: yes
- Related Files: ui-tui/package.json, ui-tui/packages/hermes-ink/package.json

### Resolution

Built the local Ink workspace and ran the suite with SSH marker variables unset.

---

## [ERR-20260718-011] hermes-ink-node26-child-process-types

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: frontend

### Summary

Node 26 typings rejected a readonly conditional stdio tuple in `execFileNoThrow`.

### Error

```
Type 'readonly ["pipe", "ignore", "ignore"]' is not assignable to type 'StdioOptions'.
```

### Context

- The error appeared after installing locked TUI dependencies and running `tsc --noEmit`.
- The utility conditionally chooses piped or ignored output for spawned processes.

### Suggested Fix

Type the conditional as mutable `StdioOptions` and the result as `ChildProcess`.

### Metadata

- Reproducible: yes
- Related Files: ui-tui/packages/hermes-ink/src/utils/execFileNoThrow.ts

### Resolution

Typed stdio as mutable `StdioOptions`; the TUI TypeScript check now passes.

---

## [ERR-20260718-010] tui-typecheck-dependencies-missing

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary

The TUI type-check could not start because workspace dependencies were absent.

### Error

```
sh: tsc: command not found
```

### Context

- `npm run type-check` was run in `ui-tui` after removing the Skills Hub overlay.
- The worktree did not contain `node_modules`.

### Suggested Fix

Install the repository's locked npm workspace dependencies and rerun type-check.

### Metadata

- Reproducible: yes
- Related Files: package-lock.json, ui-tui/package.json

### Resolution

Installed the locked npm workspace dependencies and reran type-check successfully.

---

## [ERR-20260718-005] delegation-heartbeat-timing-flake

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary

The timing-sensitive delegation heartbeat test observed 6 callbacks where it requires more than 6.

### Resolution

The unchanged test passed immediately in isolation; no product code was altered for the scheduler jitter.

---

## [ERR-20260718-009] zsh-reserved-status-variable

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary

A pytest collection wrapper assigned to zsh's read-only `status` parameter.

### Error

```
zsh:1: read-only variable: status
```

### Context

- The command captured pytest's exit code after redirecting collection output.
- The failure happened in shell control logic; pytest had already produced its output.

### Suggested Fix

Use a task-specific variable such as `pytest_exit_code` in zsh commands.

### Metadata

- Reproducible: yes
- Related Files: tests/
- See Also: ERR-20260718-008

### Resolution

- **Resolved**: 2026-07-18T00:00:00+08:00
- **Notes**: Renamed the shell variable before rerunning collection.

---

## [ERR-20260718-004] stale-focused-test-paths

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary

A focused test command named two runtime-provider test files that no longer exist after checklist pruning.

### Error

```
ERROR: file or directory not found: tests/test_runtime_provider.py
```

### Resolution

Used `rg --files tests` to resolve the remaining transport test path before rerunning.

---

## [ERR-20260718-003] shifted-line-runtime-removal

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: high
**Status**: resolved
**Area**: backend

### Summary

Sequential line-number deletions shifted `run_agent.py` and clipped retained activity, memory-shutdown, and LM Studio methods.

### Error

```
SyntaxError: '{' was never closed
```

### Context

- Three deletion ranges were calculated before earlier ranges changed line positions.
- A compile check caught the damage immediately.

### Resolution

- Restored retained blocks from the current commit using named function anchors.
- Subsequent mechanical edits must use semantic start/end markers, never mutable line numbers.

---

## [ERR-20260718-002] focused-moa-stale-test

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary

The retained MoA test slice still referenced a heavy-skill guard file removed by the approved checklist.

### Error

```
FileNotFoundError: tools/skills_guard.py
```

### Context

- MoA now uses the retained active Codex/custom runtime.
- A shared content-normalization test also revealed two generic reasoning formats that should remain supported.

### Resolution

- Removed only the stale source-file assertion.
- Kept and repaired generic reasoning normalization for compatible endpoints.

---

## [ERR-20260718-007] create-goal-after-resume

**Logged**: 2026-07-18T08:01:12+08:00
**Priority**: low
**Status**: resolved
**Area**: infra

### Summary

The goal service rejected a replacement goal after the user resumed a goal
that had previously been marked blocked.

### Error

```
cannot create a new goal because this thread has an unfinished goal;
complete the existing goal first
```

### Context

- The user explicitly asked to set the goal again with an approved checklist.
- The prior goal was blocked only while waiting for that product decision.
- Goal tooling exposes no manual resume operation and forbids falsely marking
  incomplete work complete.

### Suggested Fix

Continue the user-resumed work under the existing goal and use the approved
checklist as its authoritative scope.

### Metadata

- Reproducible: yes
- Related Files: .plans/approved-feature-cleanup.md

### Resolution

- **Resolved**: 2026-07-18T08:01:12+08:00
- **Notes**: Kept the existing goal unfinished and resumed implementation
  without misreporting its status.

---

## [ERR-20260718-008] zsh-special-path-variable

**Logged**: 2026-07-18T00:25:24Z
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary

A shell audit loop used zsh's special `path` variable and temporarily broke
command lookup inside the loop.

### Error

```
The probe falsely reported every retained file as missing from HEAD and the
working tree.
```

### Context

- The loop assigned each filename to a variable named `path`.
- In zsh, `path` is tied to `PATH`, so the assignment removed Git and other
  commands from lookup for each iteration.

### Suggested Fix

Use a task-specific variable such as `audit_file` in zsh loops.

### Metadata

- Reproducible: yes
- Related Files: none
- See Also: ERR-20260717-002

### Resolution

- **Resolved**: 2026-07-18T00:25:24Z
- **Notes**: Re-ran the probe with a direct path check and will avoid zsh's
  special `path` variable in subsequent loops.

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
## [ERR-20260718-001] auth-cleanup-patch-context

**Logged**: 2026-07-18T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: backend

### Summary

A multi-hunk auth cleanup patch used stale comment context after earlier edits.

### Error

```
apply_patch verification failed: Failed to find expected lines
```

### Context

- The patch combined unrelated documentation and code cleanup hunks.
- Earlier reductions shifted one comment block in `hermes_cli/auth.py`.

### Suggested Fix

Split broad cleanup patches into small hunks anchored to current file content.

### Metadata

- Reproducible: no
- Related Files: hermes_cli/auth.py

### Resolution

- **Resolved**: 2026-07-18T00:00:00+08:00
- **Notes**: Re-read the current file and continued with verified small hunks.

---
## [ERR-20260718-006] Combined stale fast-test patch used a mismatched context

**Logged**: 2026-07-18
**Severity**: low
**Status**: resolved

### Summary
A combined `apply_patch` for stale TUI fast-mode tests failed because one trailing `_load_service_tier` context belonged to a different test file.

### Prevention
Patch each file independently and verify exact `rg` locations before combining unrelated contexts.
## [ERR-20260718-007] Collection found stale tests for removed surfaces

**Logged**: 2026-07-18
**Severity**: medium
**Status**: resolved

### Summary
Full pytest collection failed because retained test modules still imported the removed skill-preloading helper and a removed WSL prompt constant.

### Prevention
After deleting a public helper or constant, immediately search test imports for its symbol and either prune checked-feature tests or restore retained-platform coverage.
## [ERR-20260718-008] Multi-region provider cleanup patch missed context

**Logged**: 2026-07-18
**Severity**: low
**Status**: resolved

### Summary
A multi-region patch for gateway/CLI OpenRouter cleanup failed on one display-label context and therefore applied none of its hunks.

### Prevention
Split large cross-file cleanup patches into small file-local patches after checking exact current text.
## [ERR-20260718-009] Model-metadata cleanup patch was too broad

**Logged**: 2026-07-18
**Severity**: low
**Status**: resolved

### Summary
A broad comment-and-code cleanup patch for model metadata failed context verification before applying.

### Prevention
Use small symbol-focused patches for live metadata code, then make comment-only cleanup separately.

## [ERR-20260718-010] Provider parity tests retained removed integrations

**Logged**: 2026-07-18
**Severity**: low
**Status**: resolved

### Summary
The focused provider-parity run failed because the test module still exercised removed OpenRouter, Gemini, Nous, Kimi, and provider-routing branches.

### Prevention
When deleting provider branches, prune or retarget their parity tests in the same change while preserving Codex and custom-endpoint coverage.

## [ERR-20260718-011] Focused parity process was killed

**Logged**: 2026-07-18
**Severity**: low
**Status**: monitoring

### Summary
The first post-prune provider-parity pytest process was terminated with exit 137 after 34 passing tests, without a Python failure traceback.

### Prevention
Re-run the file through the repository's per-file isolated runner and monitor memory pressure before treating it as a code regression.

## [ERR-20260718-012] Combined vision cleanup patch missed a comment

**Logged**: 2026-07-18
**Severity**: low
**Status**: resolved

### Summary
A combined test-and-comment patch failed because the image-routing comment text differed slightly from the expected context.

### Prevention
Apply behavioral test updates separately from comment-only cleanup and inspect exact lines first.

## [ERR-20260718-013] Collection retained removed platform imports

**Logged**: 2026-07-18
**Severity**: low
**Status**: resolved

### Summary
Full pytest collection found four test modules importing removed native Windows,
WSL, or Termux helpers.

### Prevention
After removing a platform implementation, search the full test tree for every
deleted public symbol and platform-specific fixture before running collection.

## [ERR-20260718-014] Prompt tests expected removed model families

**Logged**: 2026-07-18
**Severity**: low
**Status**: resolved

### Summary
The focused prompt-builder run retained three assertions for removed Grok,
Qwen, and DeepSeek model families after enforcement was narrowed to GPT/Codex.

### Prevention
Audit model-family assertions whenever the retained provider/model matrix is
reduced, including constants shared by prompt construction.

## [ERR-20260718-015] Mechanical test-pruning command was misquoted

**Logged**: 2026-07-18
**Severity**: low
**Status**: resolved

### Summary
A read-only Python command used to generate an `apply_patch` rewrite passed
literal newline escapes to `python -c`, producing a syntax error.

### Prevention
Use a quoted heredoc for multiline read-only transformation scripts, then pass
their output through `apply_patch` for the actual edit.

## [ERR-20260718-016] Full isolated baseline exposed stale cleanup tests

**Logged**: 2026-07-18
**Severity**: medium
**Status**: in progress

### Summary
The first complete isolated run passed 17,865 tests and identified 705 failures
across 123 files, mostly tests for explicitly removed providers, platforms,
connectors, Skills Hub, and legacy compatibility surfaces.

### Prevention
After a checklist-driven deletion pass, run the per-file suite early and use its
failure inventory to prune checked-feature tests and repair retained contracts.

## [ERR-20260718-017] AST pruning left decorators and empty classes

**Logged**: 2026-07-18
**Severity**: low
**Status**: resolved

### Summary
The mechanical test pruning used each AST node's `lineno`, which excludes
decorator lines, and left two classes empty after all selected methods were
removed. Compile checks caught the resulting syntax errors immediately.

### Prevention
When generating removal ranges from AST nodes, begin at the earliest decorator
line and remove parent classes whose bodies become empty; always run compileall
after mechanical pruning.
## ERR-021: Gateway cwd cleanup patch used stale exception text

- **Date:** 2026-07-18
- **Context:** Removing the legacy `MESSAGING_CWD` fallback.
- **Error:** `apply_patch` could not match the warning block because the live code logged `_bootstrap_exc` instead of silently passing.
- **Resolution:** Re-read the exact block and applied a narrower patch against the current text.
- **Status:** Resolved
## ERR-022: Multi-file legacy alias patch had an over-specific setup comment match

- **Date:** 2026-07-18
- **Context:** Removing remaining provider-field aliases.
- **Error:** A multi-file `apply_patch` was rejected while matching an unrelated setup comment, so none of its edits applied.
- **Resolution:** Split behavior changes from comment cleanup and used smaller exact patches.
- **Status:** Resolved
## ERR-023: `apply_patch` delete-file syntax included content lines

- **Date:** 2026-07-18
- **Context:** Removing the test file dedicated to deleted provider grouping.
- **Error:** The custom patch parser rejected content lines after `*** Delete File` as an invalid hunk.
- **Resolution:** Used the delete-file directive without a generated content hunk.
- **Status:** Resolved
## ERR-024: Targeted pytest command referenced a nonexistent runtime-provider test file

- **Date:** 2026-07-18
- **Context:** First focused validation after canonical provider cleanup.
- **Error:** Pytest exited with code 4 because `tests/hermes_cli/test_runtime_provider.py` does not exist.
- **Resolution:** Located matching test files with `rg --files` and reran the valid targeted set.
- **Status:** Resolved
## ERR-025: Canonical config save refactor left a stale local variable

- **Date:** 2026-07-18
- **Context:** Removing root-level config alias normalization.
- **Error:** Focused tests found `save_config()` still referenced deleted `current_normalized`, causing `NameError` after every successful atomic write.
- **Resolution:** Restored an explicitly named current config snapshot without legacy normalization and kept template-preserving output separate.
- **Status:** Resolved
## ERR-026: Test cleanup patch mixed prose and parameter-case edits

- **Date:** 2026-07-18
- **Context:** Updating provider tests to the canonical model-map schema.
- **Error:** A combined patch failed on a docstring match before reaching the behavioral edits.
- **Resolution:** Split the field/case updates from optional prose cleanup.
- **Status:** Resolved

## ERR-027: Referenced project rule files were absent

- **Date:** 2026-07-18
- **Context:** Rechecking the repository-specific workflow instructions before final validation.
- **Error:** The supplied `AGENTS.md` references `rules/workflow.md`, `rules/agent-usage.md`, and `rules/task-tracking.md`, but this checkout has no `rules/` directory.
- **Resolution:** Continued under the complete inline `AGENTS.md` requirements and the approved design document, which already require staged implementation, review, tracking, and validation.
- **Status:** Resolved

## ERR-028: Parallel test runner rejected advertised pytest flags

- **Date:** 2026-07-18
- **Context:** Starting the complete isolated test suite.
- **Error:** `scripts/run_tests_parallel.py` documents arbitrary pytest pass-through arguments, but its current parser rejected `-q --tb=short` as unknown options.
- **Resolution:** Reran the project runner without optional pytest flags; its per-file subprocesses already capture failure details.
- **Status:** Resolved

## ERR-029: Combined stale-test patch used inexact context

- **Date:** 2026-07-18
- **Context:** Adapting retained custom-provider tests and pruning tests for removed credential stores.
- **Error:** A combined `apply_patch` could not match a wrapped file-safety docstring; an immediate follow-up also targeted provider blocks already changed by the first partial application.
- **Resolution:** Re-read the live files, then applied small exact hunks against their current content.
- **Status:** Resolved

## ERR-030: Two targeted test commands referenced stale paths

- **Date:** 2026-07-18
- **Context:** Validating retained gateway, compression, browser, and file slices.
- **Error:** Two pytest invocations included test filenames that no longer exist in this checkout, so collection stopped before running valid targets.
- **Resolution:** Located current test paths with `rg --files` and reran the intended slices using the live filenames.
- **Status:** Resolved

## ERR-031: Browser test patch briefly produced a collection error

- **Date:** 2026-07-18
- **Context:** Updating a retained local-browser launch-hint assertion.
- **Error:** The first collection attempt reported an indentation error at the edited assertion.
- **Resolution:** Re-read and compiled the file, confirmed the corrected indentation, then reran the slice successfully.
- **Status:** Resolved

## ERR-032: Platform-skip test initially omitted its import

- **Date:** 2026-07-18
- **Context:** Making Linux-only `systemctl` guard self-tests portable to macOS.
- **Error:** The first patch used `shutil.which()` without importing `shutil`, causing four `NameError` failures.
- **Resolution:** Added the missing standard-library import and reran the slice.
- **Status:** Resolved

## ERR-033: TUI tests inherited SSH state and the wrong Python

- **Date:** 2026-07-18
- **Context:** Final TypeScript TUI validation.
- **Error:** The first Vitest run inherited an SSH marker, so local terminal-setup tests exited through the remote-session guard; its Python parity subprocess also used a Python without the project dependencies. One expensive cursor regression timed out at the default five seconds.
- **Resolution:** Kept the successful TypeScript type-check result and reran tests with SSH markers removed, `HERMES_PYTHON` pointed at `.venv/bin/python`, and a larger test timeout.
- **Status:** Resolved

## ERR-034: EOF cleanup initially parsed line numbers as filenames

- **Date:** 2026-07-18
- **Context:** Clearing `git diff --check` warnings after mechanical test pruning.
- **Error:** The first pipeline retained `:line` suffixes from `git diff --check`, so Perl could not open the reported paths.
- **Resolution:** Extracted the filename field before applying the mechanical trailing-newline normalization; `git diff --check` is clean.
- **Status:** Resolved

## ERR-035: Dependency lock was stale after cleanup

- **Date:** 2026-07-18
- **Context:** Final package validation.
- **Error:** `uv lock --check` reported that `uv.lock` did not match the cleaned `pyproject.toml`, so the chained package build did not start.
- **Resolution:** Regenerated the lockfile with `uv lock`, rechecked it, then ran the package build separately.
- **Status:** Resolved

## ERR-036: Build frontend was not installed in the project venv

- **Date:** 2026-07-18
- **Context:** Final wheel and source-distribution validation.
- **Error:** `.venv/bin/python -m build` failed because the optional `build` frontend is not installed in the development environment.
- **Resolution:** Used the available `uv build` frontend instead, without adding a runtime dependency solely for packaging validation.
- **Status:** Resolved
## ERR-033: README cleanup patch used an inexact provider URL

- **Date:** 2026-07-18
- **Context:** Rewriting the project overview for the retained Codex/custom-only provider surface.
- **Error:** The first combined patch used an inexact Xiaomi URL in its context and did not apply.
- **Resolution:** Re-read the live README and applied the cleanup using exact current text.
- **Status:** Resolved

## ERR-034: Combined installer cleanup patch used inexact package-data context

- **Date:** 2026-07-18
- **Context:** Removing the legacy bootstrap and dashboard package-data entries.
- **Error:** A combined patch failed because the live `pyproject.toml` comments differed from the assumed context.
- **Resolution:** Re-read the live section and applied smaller exact hunks.
- **Status:** Resolved

## ERR-035: Error-log update included an empty patch hunk

- **Date:** 2026-07-18
- **Context:** Updating stale file-safety assertions while recording an earlier patch mismatch.
- **Error:** `apply_patch` rejected an empty `Update File` hunk for this log.
- **Resolution:** Combined the assertion edits with a complete, valid append hunk.
- **Status:** Resolved

## ERR-036: Multi-file stale-reference patch used mismatched browser text

- **Date:** 2026-07-18
- **Context:** Removing references to deleted execution and browser backends.
- **Error:** A broad multi-file patch failed while matching a browser CDP message.
- **Resolution:** Split the cleanup into smaller exact file-level patches.
- **Status:** Resolved

## ERR-037: Removed-backend prose patch used an incomplete paragraph

- **Date:** 2026-07-18
- **Context:** Removing the last `_stdin_mode` documentation after deleting SDK backends.
- **Error:** The patch omitted two live continuation lines and did not match.
- **Resolution:** Re-read the exact paragraph and replaced it with a retained-backend description.
- **Status:** Resolved
