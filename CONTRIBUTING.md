# Contributing to Hermes Lite

Hermes Lite intentionally has a narrow product boundary. Bug fixes,
maintainability improvements, and security hardening within that boundary are
welcome. Feature requests for plugins, skills, MCP, memory providers,
messaging, dashboards, schedulers, media, or hosted account services belong in
the full upstream project.

Before changing code, read `AGENTS.md`. Non-trivial changes need an approved
design in `.plans/` with goals, non-goals, risks, impact, alternatives, and
success criteria.

Set up a development environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Before submitting a change:

```bash
scripts/run_tests.sh
ruff check .
python -m compileall -q .
```

Review the full diff after validation. Explain behavior changes, security
impact, and what was actually tested.
