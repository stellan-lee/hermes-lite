# Upstream feature-port record

## Provenance

- Official upstream: https://github.com/NousResearch/hermes-agent
- Local starting baseline: `8a31768825a9fed37d7d0853a3d80b00cd1949f6`
- Upstream inspected through: `d2c81eb681dea1382fbd1ed403f58320d5aef575`
- Port branch: `codex/feat-upstream-feature-port`
- Method: manual transplant and fork-specific adaptation. No commits were cherry-picked because the histories and several command/UI modules have diverged.

## Imported upstream work

### Background subagents

- PR #40946
- PR #46968
- PR #49734
- PR #51441
- PR #51485
- Persist-background-completions commit `67f4e1b4a9df36a6900f2dbc3cf5b71e298c3a7f`

Implemented top-level automatic background delegation, synchronous nested/orchestrator delegation, consolidated parallel batch completions, lifecycle interruption, CLI/gateway/TUI status, durable SQLite completion persistence and delivery acknowledgements, restart recovery, and session/UI routing metadata. The shared daemon executor prerequisite was also ported.

### `/learn`

- PR #51506
- PR #52372

Implemented the final standards-guided learning prompt and command routing in the classic CLI, messaging gateway, TUI command dispatcher, dashboard chat handoff, and Skills-page entry point.

### CLI/TUI `/journey`

- PR #55555
- PR #55859

Implemented the shared learning graph, terminal renderer, skill/memory edit and delete mutations, `hermes journey` (plus aliases), classic `/journey`, the full-screen TUI journey overlay, editor flow, RPC methods, and focused TUI tests.

### Automation Blueprints

- PR #41309

Implemented the blueprint catalog and filling logic, skill-frontmatter blueprint bridge, suggested-automation store/catalog, classifier helper, classic CLI and gateway commands, skill-install suggestion registration, dashboard API/gallery, cron-page integration, configuration, packaging, and focused tests.

### Image-to-image/reference-image editing

- PR #48705

Implemented the common provider editing contract, normalized reference images, provider capability reporting, FAL edit routing/model metadata, dynamic tool descriptions, and editing support for FAL, OpenAI, OpenAI Codex, xAI, and Krea. Existing Krea `image_style_references` behavior is preserved and unified with `image_url` / `reference_image_urls`.

### Session management

- PR #49739
- PR #52658
- `1fbf48d4ad827253a5637b0444a00beb38e22b2f`
- `4f9485a95dc555aaa2ff32e9ca0969b663c7134e`
- `4663456996388e1814dbccb5b535dbfd4d8c8d32`
- `602fe1c15d59c763a796976d57675c98837228f8`
- `0c4aed2499c37372cd07a127ee10bd74aec60cf4`
- `b5f0e451c15dd3346a593406b1551cb599ee215c`
- `b51d365ef02a952f9e94f3be94c7eed84bf4daf5`

Implemented default-on in-place compaction with one durable session ID, non-destructive soft archival of pre-compaction turns, live-context filtering, archived-turn searchability, compaction-boundary hooks/signals, gateway auto/hygiene/manual-compression handling, workspace grouping/filtering, resume cwd restoration with opt-out, SessionDB import, and dashboard JSON/JSONL import.

## Fork adaptations and omissions

- No desktop application code was imported from the journey, blueprint, or session changes.
- The journey mutation HTTP endpoints used by upstream desktop were omitted; this port targets the requested CLI and TUI journey surfaces.
- Upstream `gateway/slash_commands.py` behavior was integrated into this fork's `gateway/run.py`; upstream `hermes_cli/cli_commands_mixin.py` behavior was integrated into `cli.py` because those split modules do not exist here.
- The older dashboard Skills page lacks upstream's editor/dialog composition. Its Learn entry uses a compact prompt and then hands the request to the same `/learn` chat path.
- This checkout's website contains only `website/src`, not the upstream docs/catalog build tree. Documentation generators, Docusaurus catalog components, and website-only reference pages from PRs #41309, #48705, and #51506 were not imported.
- Dashboard session endpoints in this fork are not profile-scoped. Session import therefore targets the active/default SessionDB and ignores an optional profile value.
- This fork's session schema stores `cwd` but not `git_branch` / `git_repo_root`. Imported sessions retain `cwd`; unsupported exported git metadata is ignored. The workspace helper still prefers git-root fields when supplied by richer row dictionaries and otherwise falls back to `cwd`.
- Upstream test expectations were adapted to the fork's cwd-only session schema and absent website-doc generator.
- No live provider request, paid image generation/edit, or real messaging-platform delivery was executed.

## Independent review fixes

The port was corrected after an independent review:

- In-place compaction now rebases the SQLite flush cursor after installing the compacted live transcript, preventing the normal end-of-turn flush from duplicating it.
- Gateway hygiene and manual compression no longer hard-rewrite SQLite after a successful in-place soft archive. Partial manual compression uses rotation because its preserved tail is rejoined outside the agent.
- Rotating compression now creates a child with an explicit durable `continuation_type` marker. Resume, gateway/TUI ownership, classic-CLI completion routing, and cancellation follow only marked compression lineage, excluding branch and delegate children; legacy rows receive a conservative migration fallback.
- Gateway rotation publishes its new route only after the compressed child transcript is durably written. SQLite or session-index save failures roll back the unpublished child and retain the original parent route.
- Failed in-place compaction persistence now rolls back the in-memory compressed result, system prompt cache, flush cursor, compaction signal, and context-engine counters; the original active transcript is returned and the compression lock is released.
- Session export/import includes inactive compacted rows and preserves each row's `active` / `compacted` state while keeping session counters scoped to active rows.
- Async delegation delivery requires durable parent and/or TUI-origin ownership, while verified legacy compression descendants remain eligible. `/new`, session switches/branches, TUI close, gateway reset/expiry, and CLI close interrupt the ending session's children; stale completions are not injected into a competing live session.
- Classic CLI durable completions remain pending until their synthetic agent turn returns successfully; queueing alone no longer acknowledges delivery.
- Classic CLI completions launched before session rotation are accepted by the marked compression continuation while unrelated children remain ineligible.
- TUI durable completions now use a turn-completion callback and are acknowledged only after successful synthetic-turn processing/persistence across the live poller, shutdown drain, and post-turn drain. Failed turns remain pending.
- Rejected background dispatch reattaches children before synchronous fallback so parent interruption still propagates.
- Journey memory IDs are content-derived instead of positional. Memory mutations are serialized across threads and processes, verify the current content identity under the lock, and use fsync plus atomic replacement.
- Suggested-automation acceptance uses a cross-process atomic `pending` → `accepting` claim, releases the claim lock before cron creation, and rolls back to `pending` if cron job creation fails.
- Ephemeral image URL downloads stream into a sibling temporary file, fsync, and atomically publish the final cache path; failed streams remove their partial files.
- Krea converts local reference-image paths to data URLs while preserving public URL, data URL, and legacy reference-object behavior.
- Dashboard blueprint delivery options include `all`.
- The unrelated Sessions page message-loading and search-state rewrites were removed; the import UI remains.

## Validation

Successful:

- Review-touched Python modules and regression tests compile:
  ```bash
  venv/bin/python -m py_compile \
    utils.py agent/conversation_compression.py agent/image_gen_provider.py \
    agent/learning_graph.py agent/learning_mutations.py cli.py \
    cron/suggestions.py gateway/run.py hermes_state.py \
    plugins/image_gen/krea/__init__.py tools/delegate_tool.py \
    tui_gateway/server.py \
    tests/run_agent/test_860_dedup.py tests/agent/test_learning_mutations.py \
    tests/agent/test_save_url_image.py tests/gateway/test_compress_command.py \
    tests/gateway/test_session_hygiene.py \
    tests/gateway/test_session_boundary_hooks.py \
    tests/cron/test_suggestions.py tests/cron/test_blueprint_catalog.py \
    tests/tools/test_async_delegation.py \
    tests/tools/test_image_generation_image_to_image.py \
    tests/cli/test_cli_new_session.py tests/test_hermes_state.py \
    tests/test_tui_gateway_server.py tests/hermes_cli/test_web_server.py
  ```
- Isolated-`HERMES_HOME` direct assertion smokes passed for cross-process suggestion claiming, concurrent journey edits without lost updates, in-place compression DB-failure rollback/lock release, gateway archived-row preservation, TUI completion success/failure signaling, and atomic image stream publication/cleanup. The standalone multiprocessing smoke used `fork`; the checked-in regressions use `spawn` from real pytest modules for supported-OS coverage.
- TUI focused tests after building the local Ink package:
  - `cd ui-tui && npm run build --prefix packages/hermes-ink`
  - `cd ui-tui && npm test -- --run src/__tests__/journeyCommand.test.ts src/__tests__/statusRule.test.ts`
  - Result: 2 files, 15 tests passed.
- Dashboard session import: `cd web && npx vitest run src/lib/session-import.test.ts` — 1 file, 5 tests passed.
- Dashboard TypeScript check with the repository's TypeScript-6 deprecation suppressed:
  - `cd web && npx tsc --noEmit -p tsconfig.app.json --ignoreDeprecations 6.0`
  - Ported files passed; the command stops on an unrelated existing unused `LayoutDashboard` import in `src/pages/ConfigPage.tsx`.
- `git diff --check` — passed after the review fixes.
- All 64 changed/untracked Python files outside the user-owned `infographic/` directory compiled with the project Python 3.11 interpreter.

Environment/baseline limitations:

- Python pytest could not be run: the existing `venv` does not contain pytest. The reproducible focused command below stops immediately with `No module named pytest`; no dependency installation was attempted, and direct isolated contract tests were used instead.
  ```bash
  venv/bin/python -m pytest -q \
    tests/run_agent/test_860_dedup.py \
    tests/gateway/test_compress_command.py \
    tests/gateway/test_session_hygiene.py \
    tests/gateway/test_session_boundary_hooks.py \
    tests/test_hermes_state.py \
    tests/tools/test_async_delegation.py \
    tests/agent/test_learning_mutations.py \
    tests/agent/test_save_url_image.py \
    tests/cron/test_suggestions.py \
    tests/tools/test_image_generation_image_to_image.py \
    tests/cron/test_blueprint_catalog.py \
    tests/cli/test_cli_new_session.py \
    tests/test_tui_gateway_server.py \
    tests/hermes_cli/test_web_server.py -x
  ```
- `ui-tui npm run type-check` is blocked by pre-existing type errors in `packages/hermes-ink/src/utils/execFileNoThrow.ts`.
- TUI ESLint is blocked by the absent local `eslint-plugin-react-compiler` package.
- The default dashboard `npm run build` stops on the repository's TypeScript-6 `baseUrl` deprecation before application checking; the explicit no-emit command above bypassed that deprecation and isolated the unrelated ConfigPage error.
- No live provider call, paid image operation, real messaging delivery, or Windows runtime execution was performed.
