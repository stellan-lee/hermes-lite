# Hermes Lite Development Guide

## Purpose

Keep this repository a small, auditable local coding agent. Prefer explicit
code and fixed boundaries over discovery, compatibility layers, or optional
frameworks.

## Supported product boundary

Hermes Lite includes only:

- the Python CLI and one-shot command;
- `AIAgent` and its synchronous OpenAI-compatible tool loop;
- local SQLite sessions;
- read, write, exact-patch, search, and confirmed terminal tools;
- the five-section YAML configuration.

Do not add bundled skills, plugins, MCP, memory providers, messaging
connectors, servers, dashboards, schedulers, proprietary model protocols, or
hosted account integrations. A proposal to expand this boundary requires an
approved engineering design document.

## Architecture

```text
hermes_cli/main.py -> cli.py -> run_agent.py -> model_tools.py
                                      |              |
                                OpenAI client     tools/registry.py
cli.py -> hermes_cli/config.py
cli.py -> hermes_state.py
```

- `hermes_cli/config.py` is the only config schema and loader.
- `tools/__init__.py` explicitly imports the complete fixed tool set.
- Tool handlers return JSON strings and never raise into the agent loop.
- `hermes_state.py` stores only user and assistant messages. It is not a
  memory, retrieval, or analytics system.

## Engineering workflow

For non-trivial changes:

1. State why the change is needed and its supported boundary.
2. Write or update an engineering design in `.plans/` before implementation.
3. Implement the smallest coherent change.
4. Review the entire diff, including deletions and security boundaries.
5. Run the complete supported test suite, Ruff, compile/import checks, and a
   package build.
6. Report exactly what was reviewed and validated.

Never equate passing tests with solving the task. Inspect the final repository
and user-facing behavior as a separate step.

## Coding rules

- Python 3.11 or newer; use type hints for public functions.
- Keep runtime dependencies bounded above and directly justified.
- API keys and secrets belong in environment variables, never YAML.
- Every default config field must have a runtime consumer and a test.
- Unknown config fields must remain inert.
- Keep filesystem access beneath the configured workspace.
- Keep terminal execution non-shell, confirmed by default, time-bounded, and
  environment-limited.
- Preserve the `AIAgent.chat()` and `AIAgent.run_conversation()` entry points.
- Do not add a migration for a feature that is outside the product boundary.

## Validation

```bash
source .venv/bin/activate  # or venv/bin/activate
scripts/run_tests.sh
ruff check .
python -m compileall -q .
python -m build
```

Tests must set `HERMES_HOME` to a temporary directory and must never read or
write the real `~/.hermes` directory.
