# Preservation-First Hermes Cleanup

Status: superseded on 2026-07-18 by the user's approved checked inventory and
`.plans/approved-feature-cleanup.md`.

## Intent declaration

### WHY — motivation and problem

The current cleanup branch removed complete, working Hermes feature families
because they were optional and costly to maintain. That interpretation was
wrong. Gateways, messaging connectors, MCP, scheduling, provider support,
skills, plugins, memory, and related integration surfaces are part of the
working Hermes product even when an individual installation disables them.

The user wants genuine project hygiene: remove legacy or unused pieces without
turning Hermes into a different CLI-only product. Existing Hermes users,
integrations, and deployments are affected because the current branch deletes
their supported runtime paths rather than cleaning dead implementation.

### WHAT — scope and outcomes

The corrected cleanup will preserve the complete working Hermes baseline.
This explicitly includes gateways, messaging connectors, MCP, Codex and other
working providers, cron/scheduling, skills, plugins, memory, dashboards,
servers, terminal interfaces, and their supported configuration and tests.

In scope:

- restore the exact functional baseline that existed before the broad cleanup;
- inventory code, configuration, assets, dependencies, migrations, and tests;
- remove only items proven to have no current runtime, dynamic-registration,
  manifest, compatibility, documentation, or testing responsibility;
- remove stale default-config fields only when no consumer or compatibility
  contract exists;
- retain supported public entry points, protocols, connectors, and deployment
  modes;
- keep the existing Codex implementation rather than replacing it.

Out of scope:

- deleting an entire working feature family to reduce repository size;
- treating “optional” as synonymous with “unused”;
- removing a module solely because static import search cannot find it;
- redesigning Hermes as a CLI-only product;
- reimplementing restored features;
- changing public behavior unless needed to remove a demonstrated defect or
  dead compatibility path.

Expected outcome: the same working Hermes product with a smaller amount of
demonstrably dead or stale material, not a reduced product surface.

### HOW — approach and constraints

First restore the repository from Git history so the correction uses the
original implementations rather than reconstructed substitutes. Restore the
newest cleanup follow-up before the broad cleanup commit to avoid mixing the
selective Codex restoration with the original baseline.

Then build an evidence ledger for proposed removals. A candidate is removable
only after checking direct imports, lazy imports, plugin/provider/platform
registries, manifests, entry points, configuration readers and migrations,
documentation, packaging, deployment files, and tests. Dynamic discovery means
static reachability alone is insufficient evidence.

Apply only narrow, independently reviewable deletions. Preserve configuration
compatibility unless a field is both unconsumed and undocumented as a migration
or compatibility input. Review the complete diff for accidental feature loss,
then run the full upstream test, lint, compile/import, and package validation
appropriate to the restored repository.

The accepted trade-off is a more modest size reduction in exchange for
preserving Hermes behavior and avoiding false-positive dead-code deletion.

## Engineering design document

### 1. Background & context

Hermes uses dynamic loading and multiple runtime surfaces. Platform adapters,
providers, plugins, MCP servers, and skills may be loaded through registries or
manifests rather than ordinary imports. The prior cleanup deliberately changed
the product boundary and therefore removed these families wholesale. The user
has now rejected that boundary: those systems are foundational and must remain.

The branch contains two cleanup commits: the broad minimal-core conversion and
a follow-up that selectively restored Codex compatibility. Returning to the
working baseline is safer and more faithful than selectively rebuilding
hundreds of coupled files. The pull request base has also advanced since the
cleanup branch was created: current `origin/main` includes gateway admin
approval routing that must be preserved as part of the functional baseline.

### 2. Goals and non-goals

Goals:

- preserve all working Hermes capabilities and integrations;
- restore deleted code from history, without reimplementation;
- identify dead or stale material using explicit evidence;
- keep default configuration accurate without breaking supported setups;
- reduce maintenance burden only where behavior is unaffected;
- leave an auditable record for every deletion.

Non-goals:

- minimizing file count at the expense of capability;
- removing gateways, connectors, MCP, or other foundational systems;
- replacing dynamic extension mechanisms with fixed registries;
- changing the product identity or supported deployment shapes;
- declaring tested optional code “unused” merely because it is disabled by
  default.

### 3. Proposed design

The cleanup has two boundaries:

1. **Restoration boundary:** restore the exact pre-cleanup tree and behavior,
   then integrate the current pull-request base so newer gateway behavior is
   also preserved. No restored subsystem is redesigned during this phase.
2. **Evidence boundary:** consider individual cleanup candidates only after all
   known loading and compatibility paths have been checked.

Each proposed removal will record:

- the file, field, dependency, or asset;
- every static and dynamic lookup performed;
- whether packaging, manifests, migrations, docs, or tests reference it;
- why removal cannot disable a supported feature;
- the validation that proves behavior remains intact.

Candidates that cannot meet this standard remain in the repository. Config
cleanup follows the same rule: a default field is removed only when it has no
runtime consumer and is not an intentional compatibility input.

### 4. Alternatives considered

**Selectively restore only the newly named subsystems.** Rejected because “and
so on” indicates a broader foundational boundary, and selecting families by
guesswork risks another incomplete restoration.

**Keep the minimal branch and reimplement missing integrations.** Rejected
because the original implementations already exist in Git and the user asked
for cleanup, not replacement architecture.

**Abandon cleanup after restoring the baseline.** Rejected because it preserves
behavior but does not address the original request to remove genuinely unused
or legacy material.

### 5. Risks and open questions

- The restored upstream suite is large and may expose environment-dependent
  failures. These must be separated from regressions introduced by cleanup.
- Dynamic loading can hide consumers. Registry, manifest, entry-point, and
  migration audits are mandatory before deletion.
- “Legacy” may still mean supported compatibility. Ambiguous candidates stay
  until evidence or a product decision proves otherwise.
- Reverting the two branch commits may conflict because Codex files were
  restored selectively. Reverting newest-first preserves a recoverable,
  reviewable history and minimizes ambiguity.
- The pull-request base advanced after the cleanup branch forked. Restoration
  must include current `origin/main`, not only the cleanup commit's parent.

### 6. Impact

Gateways, messaging, MCP, scheduling, providers, plugins, skills, memory,
dashboards, servers, and deployment modes return exactly as they existed before
the cleanup. Repository size and dependency count will increase back to the
working baseline before any narrow cleanup. The final reduction will likely be
smaller, but maintenance and compatibility risk will be substantially lower.

The pull request will change from a product-boundary rewrite to a targeted
hygiene change. Restoration and cleanup will be kept logically distinct in Git
history so reviewers can verify both.

### 7. Success criteria

- the complete pre-cleanup functional baseline is restored from Git history;
- the current pull-request base, including gateway admin approval routing, is
  integrated without force-rewriting shared history;
- gateway, messaging, MCP, cron, provider, skill, plugin, memory, dashboard,
  server, and interface implementations remain present and importable;
- no supported entry point, manifest, registry item, configuration contract,
  or deployment mode is removed;
- every deletion has an evidence record showing why it is unused or obsolete;
- the full applicable upstream test suite, lint, compile/import checks, and
  package build pass, with environment-only limitations reported separately;
- the final diff is reviewed independently of test results for accidental
  capability loss;
- documentation and the pull request describe a preservation-first cleanup,
  not Hermes Lite or a CLI-only replacement.

## Approval

Implementation begins only after the user approves this corrected design.

## Read-only restoration audit

Recorded on 2026-07-18 before implementation:

- cleanup commit: `91d46949e`, parent `154404b7c`;
- Codex follow-up: `eee7b5ce7`, parent `91d46949e`;
- current pull-request base: `origin/main` at `68df3f7ae`;
- current branch versus its original base: 10 added, 49 modified, and 2,720
  deleted paths;
- the newer base commit adds gateway admin approval routing across gateway
  configuration, platform adapters, tools, documentation, and tests;
- safe restoration order: preserve the design record, revert the Codex
  follow-up, revert the broad cleanup, then integrate current `origin/main`;
- no force push or history rewrite is required.
