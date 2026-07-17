# Hermes Lite

Hermes Lite is a small local coding agent for OpenAI-compatible models. It is
the CLI and agent loop without bundled skills, general plugin discovery, MCP,
memory providers, messaging connectors, dashboards, schedulers, media
generation, or hosted account services. The original OpenAI Codex-specific
modules are retained as a narrow exception.

## What remains

- Interactive chat and one-shot prompts
- Any OpenAI-compatible chat-completions endpoint
- Local SQLite conversation sessions
- Five explicit tools: `read_file`, `write_file`, `patch`, `search_files`, and
  `terminal`
- The original Codex Responses adapter, app-server client/session, model
  discovery, runtime switch, and fixed `openai-codex` provider profile
- One YAML config and three direct runtime dependencies
- The `AIAgent.chat()` and `AIAgent.run_conversation()` Python API

The default CLI continues to use the compact chat-completions loop. The
restored Codex modules remain importable for existing Codex integrations; no
other provider catalog or extension framework is restored.

## Install

Hermes Lite requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Set an API key in the process environment or in `~/.hermes/.env`:

```bash
export OPENAI_API_KEY="..."
```

Create the minimal config:

```bash
hermes init --model your-model
```

For another OpenAI-compatible endpoint:

```bash
hermes init --model your-model --base-url https://example.com/v1
```

Then start the CLI or run one prompt:

```bash
hermes
hermes ask "Explain this repository"
```

Global overrides precede the command:

```bash
hermes --model another-model --workspace ./project ask "Review the tests"
```

## Configuration

The default path is `~/.hermes/config.yaml`. Set `HERMES_HOME` to relocate all
state or `HERMES_CONFIG` to override only the config path.

```yaml
inference:
  model: your-model
  base_url: ""
  api_key_env: OPENAI_API_KEY
  temperature: 0.2

agent:
  max_iterations: 20
  system_prompt: ""

tools:
  enabled: [read_file, write_file, patch, search_files, terminal]
  workspace: .
  terminal:
    enabled: true
    confirm: true
    timeout_seconds: 60

sessions:
  enabled: true
  resume_latest: false

logging:
  level: WARNING
  file: true
```

Environment overrides are intentionally limited:

- `HERMES_MODEL`
- `HERMES_BASE_URL`
- `HERMES_HOME`
- `HERMES_CONFIG`
- the variable named by `inference.api_key_env`

Unknown legacy config fields are ignored with a warning. They are never
migrated or interpreted.

## Commands

```text
hermes                         Start interactive chat
hermes ask <prompt>            Run one prompt
hermes init [options]          Create config.yaml
hermes config                  Print effective non-secret config
hermes sessions [list]         List local sessions
hermes sessions delete <id>    Delete one local session
hermes version                 Print the version
```

Inside interactive chat, `/new`, `/sessions`, `/help`, and `/quit` are
available.

Use `--no-tools`, `--no-terminal`, or `--no-sessions` for a narrower run. Use
`--yes` only in a trusted workspace; it bypasses terminal confirmation.

## Tool security

File tools resolve every path beneath `tools.workspace`, including symlink
resolution. Writes are atomic, and `patch` refuses to edit unless the exact
expected number of matches is present.

The terminal tool:

- accepts an argument vector, not a shell string;
- runs from a directory beneath the workspace;
- requires confirmation by default;
- has a bounded timeout and output size;
- passes only a small non-secret environment allowlist.

This is not an operating-system sandbox. An approved executable can access
anything available to the current user. Disable the terminal tool when that is
not acceptable.

## Python API

```python
import os

from run_agent import AIAgent

agent = AIAgent(
    model="your-model",
    api_key=os.environ["OPENAI_API_KEY"],
    base_url="https://example.com/v1",  # omit for the OpenAI default
    workspace=".",
    terminal_enabled=False,
)

print(agent.chat("Summarize README.md"))
```

For programmatic terminal use, pass an `approval_callback`. Without one,
confirmed terminal calls are denied.

## Development

```bash
python -m pip install -e '.[dev]'
scripts/run_tests.sh
ruff check .
```

The complete cleanup rationale and success criteria are recorded in
`.plans/hermes-lite-cleanup.md`.

## Deliberately removed

Hermes Lite does not contain compatibility shims for upstream skills, general
plugins, MCP servers, memory engines, gateways, messaging platforms, browser
control, computer use, voice/image/video generation, cron jobs, ACP,
dashboard/TUI bridges, provider catalogs other than the fixed OpenAI Codex
profile, or Nous account and portal integrations. Use the full upstream Hermes
Agent project if those are required.

## License

MIT. See `LICENSE` for the retained legal attribution.
