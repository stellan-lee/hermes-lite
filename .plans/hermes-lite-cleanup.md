# Hermes Lite Cleanup

Status: superseded on 2026-07-18 by
`.plans/preservation-first-cleanup.md` after the user clarified that working
Hermes subsystems are foundational and must not be removed as cleanup.

Historical status: approved by the user's direct-execution request on
2026-07-17 under an incorrect interpretation of the desired product boundary.

## Intent declaration

### WHY — motivation and problem

The repository currently ships several products at once: a local agent, two
terminal interfaces, a web dashboard, messaging gateways, an API server, an
editor protocol adapter, schedulers, provider catalogs, MCP clients and
servers, skills, plugins, memory engines, media generation, and Nous account
services. Most of those surfaces are optional at runtime, but they still add
configuration, dependencies, tests, discovery rules, security boundaries, and
maintenance cost to every checkout and release. Users who only need a local
coding agent must understand and carry the whole platform.

This cleanup is for users and maintainers who want Hermes to remain a small,
auditable local agent. Disabling features in configuration is insufficient:
disabled code, schemas, migrations, dependencies, and documentation still
create coupling and supply-chain exposure.

### WHAT — scope and outcomes

The resulting product is a single Python application with:

- an interactive CLI and a one-shot command;
- an OpenAI-compatible chat-completions client configurable with a model,
  base URL, and environment-based API key;
- persistent local conversation sessions;
- five built-in local tools: file read, file write, exact patch, file search,
  and terminal execution;
- a small YAML configuration with only settings consumed by that runtime;
- a stable `AIAgent.chat()` and `AIAgent.run_conversation()` embedding surface.

In scope:

- remove all bundled and optional skills and their loaders;
- remove all bundled plugins and plugin discovery;
- remove MCP client/server/OAuth/configuration support;
- remove external and built-in memory/learning/curator systems;
- remove messaging platforms, gateway, dashboard, API-server connector, cron,
  ACP, browser/computer-use, voice/media generation, and the Node TUI;
- remove proprietary provider adapters and catalogs while retaining generic
  OpenAI-compatible endpoints and the user's requested pre-cleanup OpenAI
  Codex-specific compatibility modules;
- remove Nous account, subscription, portal, proxy, rate-guard, achievement,
  and hosted-service integration code;
- replace default configuration, packaging metadata, tests, and documentation
  with the minimal supported surface;
- delete obsolete compatibility migrations and feature-specific assets.

Out of scope:

- preserving configuration compatibility for removed optional features;
- preserving messaging, dashboard, MCP, plugin, skill, or memory APIs;
- supporting provider-specific protocols other than the retained OpenAI Codex
  Responses/app-server exception;
- publishing a package or changing legal attribution in the MIT license;
- adding a new extension framework to replace the removed frameworks.

Expected outcome: a coherent local agent rather than a large application with
most capabilities switched off.

### HOW — approach and constraints

Use a replacement-at-the-boundary approach. Preserve the small public core
(`AIAgent`, command-line entry points, local session concept), replace its
implementation with focused modules, and delete optional subsystems together
with their tests and dependencies. Configuration is validated from one default
schema and unknown legacy keys are ignored with a warning rather than migrated.

The tool boundary is deliberately fixed and table-driven. File tools are
restricted to the configured workspace. Terminal execution is disabled for
non-interactive embedding unless explicitly enabled, and interactive CLI runs
request confirmation. API keys remain environment-only.

The accepted trade-off is intentional feature loss in return for a smaller
dependency and security surface. A generic OpenAI-compatible endpoint covers
the common provider case. The retained Codex profile is fixed and does not
reopen arbitrary provider or user-plugin discovery.

## Engineering design document

### 1. Background & context

Hermes grew around many independently optional integrations. Their dynamic
discovery mechanisms make conventional dead-code removal unreliable: a module
can appear unreferenced while still being loaded through a manifest or registry.
The cleanup therefore changes the supported product boundary first and removes
whole feature families, rather than trying to infer runtime usage from imports.

The repository's development guide requires maintainable root-cause changes,
review, and validation. Its referenced `rules/*.md` files are absent in this
checkout, so the guide itself and this design are the available local workflow
authority.

### 2. Goals and non-goals

Goals:

- make the default install sufficient for the entire supported product;
- keep runtime dependencies few, bounded, and directly justified;
- ensure every default configuration field has a runtime consumer;
- eliminate dynamic extension and connector discovery;
- retain a useful local engineering agent and embedding API;
- make the full supported test suite fast enough to run routinely.

Non-goals:

- feature parity with upstream Hermes Agent;
- transparent migration of removed configuration;
- a compatibility shim for deleted imports;
- graphical, mobile, server, or messaging interfaces;
- autonomous background work or multi-agent delegation.

### 3. Proposed design

`hermes_cli.main` owns argument parsing and the interactive loop. It loads the
single config document, creates an `AIAgent`, and optionally opens or resumes a
session. `AIAgent` owns the synchronous chat-completions loop, converts model
tool calls into calls to `model_tools`, and returns both a final response and
OpenAI-format messages. `model_tools` exposes the fixed registry from `tools`.
`SessionDB` stores session metadata and messages in SQLite using only the Python
standard library.

Configuration contains these responsibilities only:

- inference: model, base URL, API-key environment variable, temperature;
- agent: system prompt and maximum tool iterations;
- tools: enabled names, workspace, terminal enablement and confirmation;
- sessions: persistence and default resume behavior;
- logging: level and file enablement.

Unknown keys are reported once so legacy configuration is visible but cannot
silently influence the runtime. There are no config migrations.

Tool flow:

1. The model emits a tool call from the fixed schema list.
2. `model_tools` validates the name and JSON object arguments.
3. The handler resolves paths beneath the workspace or, for terminal, checks
   enablement and obtains approval.
4. The JSON result is appended as a tool message.
5. The loop continues until a text response or the iteration limit.

### 4. Alternatives considered

Incrementally disable optional features while retaining their modules was
rejected because it leaves the dependency, discovery, migration, testing, and
security burden intact.

Keeping plugin, skill, or MCP loaders but shipping an empty catalog was also
rejected. Those loaders are themselves substantial product surfaces and would
keep many configuration and failure modes that the cleanup is intended to
remove.

Removing only files reported as statically unreachable was rejected because
the current repository relies heavily on dynamic registration and imports.

### 5. Risks and open questions

- Existing users with advanced configuration will lose those capabilities.
  Mitigation: document the supported keys and warn on ignored legacy keys.
- Replacing intertwined core modules can introduce behavior regressions.
  Mitigation: preserve the public embedding methods and test the model/tool loop
  with a deterministic fake client.
- Terminal execution is high risk. Mitigation: workspace scoping, explicit
  enablement, interactive confirmation, timeouts, and no shell for file tools.
- Some OpenAI-compatible providers differ subtly. Mitigation: keep `base_url`
  generic and avoid provider-specific assumptions beyond chat completions.
- Legal attribution is not a removable product component. The MIT license is
  retained unchanged.

### 6. Impact

Install size, import time, configuration size, dependency count, and audit
surface should fall sharply. The application becomes CLI-only and loses all
background/server integrations. Maintenance shifts from many dynamic extension
contracts to a small fixed API. Existing advanced installations require the
upstream project rather than an in-place migration.

### 7. Success criteria

- no tracked `skills`, `optional-skills`, `gateway`, `web`, `ui-tui`,
  `tui_gateway`, `cron`, or `acp_adapter` implementation trees, and no plugin
  implementation other than the fixed OpenAI Codex provider profile;
- no MCP, memory-provider, connector, plugin, skill, or Nous service settings in
  the default configuration;
- no runtime dependency that is only used by a removed feature;
- package build and clean installation succeed;
- CLI help, one-shot argument handling, config loading, session persistence,
  path containment, terminal approval, and the complete mocked agent tool loop
  are tested;
- source review finds no stale imports, entry points, manifests, or user-facing
  documentation for removed features;
- the supported test suite and static syntax/import checks pass.

## Task tracking

- [x] Inventory feature families and define the product boundary.
- [x] Record the approved architecture and success criteria.
- [x] Implement the minimal runtime and configuration.
- [x] Remove excluded feature trees, assets, dependencies, and entry points.
- [x] Replace the tests and user documentation.
- [x] Review all changes against the design and security constraints.
- [x] Run full validation and audit the final repository footprint.
- [x] Selectively restore only the requested OpenAI Codex compatibility
  components and repeat the full review and validation.

## Final validation record

- 203 tests pass on Python 3.14 and the declared minimum Python 3.11.
- Ruff check and format validation pass on Python 3.11 and 3.14.
- Bytecode compilation and `git diff --check HEAD` pass.
- `uv lock` and warning-free sdist/wheel builds pass.
- An isolated wheel install verifies both console entry points, the fixed
  `openai-codex` provider and `codex_responses` transport, Codex model/runtime
  imports, and Codex CLI detection at version 0.144.1.
- The final wheel contains no removed cron, gateway, skill, memory, MCP, Nous,
  or unrelated provider implementation path.
