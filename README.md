<p align="center">
  <img src="assets/banner.png" alt="Marlow Agent" width="100%">
</p>

# Marlow Agent ☤

<p align="center">
  <a href="https://github.com/stellan-lee/Marlow"><img src="https://img.shields.io/badge/Source-GitHub-181717?style=for-the-badge&logo=github" alt="Source repository"></a>
  <a href="https://github.com/stellan-lee/Marlow/issues"><img src="https://img.shields.io/badge/Issues-GitHub-blue?style=for-the-badge&logo=github" alt="Issue tracker"></a>
  <a href="https://github.com/stellan-lee/Marlow/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
</p>

**A self-improving AI agent with a built-in learning loop.** Marlow creates skills from experience, improves them during use, searches past conversations, and builds a deepening model of who you are across sessions. Run it locally, on a cloud VM, or through a messaging gateway.

Use a Codex subscription or any local/custom OpenAI-compatible endpoint. Switch with `marlow model`.

<table>
<tr><td><b>A real terminal interface</b></td><td>Full TUI with multiline editing, slash-command autocomplete, conversation history, interrupt-and-redirect, and streaming tool output.</td></tr>
<tr><td><b>Lives where you do</b></td><td>Telegram, Discord, Slack, Feishu, Email, and CLI — all from a single gateway process. Voice memo transcription and cross-platform conversation continuity.</td></tr>
<tr><td><b>A closed learning loop</b></td><td>Agent-curated memory with periodic nudges. Autonomous skill creation after complex tasks. Skills self-improve during use. FTS5 session search with LLM summarization for cross-session recall. <a href="https://github.com/plastic-labs/honcho">Honcho</a> dialectic user modeling. Compatible with the <a href="https://agentskills.io">agentskills.io</a> open standard.</td></tr>
<tr><td><b>Scheduled automations</b></td><td>Built-in cron scheduler with delivery to any platform. Daily reports, nightly backups, weekly audits — all in natural language, running unattended.</td></tr>
<tr><td><b>Delegates and parallelizes</b></td><td>Spawn isolated subagents for parallel workstreams. Write Python scripts that call tools via RPC, collapsing multi-step pipelines into zero-context-cost turns.</td></tr>
<tr><td><b>Runs where you work</b></td><td>Local, Docker, and SSH terminal backends cover direct development, isolated containers, and remote hosts.</td></tr>
<tr><td><b>Research-ready</b></td><td>Batch trajectory generation, trajectory compression for training the next generation of tool-calling models.</td></tr>
</table>

---

## Quick Install

### Linux and macOS

```bash
curl -fsSL https://raw.githubusercontent.com/stellan-lee/Marlow/main/scripts/install.sh | bash
```

If you are upgrading a pre-Marlow installation, run the installer directly
instead of using the old `hermes update` command. It copies missing user state
from `~/.hermes` into `~/.marlow`, excludes the obsolete source checkout, and
keeps the original directory available for rollback. Use `marlow update` after
that one-time migration.

After installation:

```bash
source ~/.bashrc    # reload shell (or: source ~/.zshrc)
marlow              # start chatting!
```

---

## Getting Started

```bash
marlow              # Interactive CLI — start a conversation
marlow model        # Choose your LLM provider and model
marlow tools        # Configure which tools are enabled
marlow config set   # Set individual config values
marlow gateway      # Start the messaging gateway (Telegram, Discord, etc.)
marlow setup        # Run the full setup wizard (configures everything at once)
marlow update       # Update to the latest version
marlow doctor       # Diagnose any issues
```

Use `marlow --help`, `marlow setup`, and the guides in this repository for configuration details.

---

## CLI vs Messaging Quick Reference

Marlow has two entry points: start the terminal UI with `marlow`, or run the gateway and talk to it from Telegram, Discord, Slack, Feishu, or Email. Once you're in a conversation, many slash commands are shared across both interfaces.

| Action                         | CLI                                           | Messaging platforms                                                              |
| ------------------------------ | --------------------------------------------- | -------------------------------------------------------------------------------- |
| Start chatting                 | `marlow`                                      | Run `marlow gateway setup` + `marlow gateway start`, then send the bot a message |
| Start fresh conversation       | `/new` or `/reset`                            | `/new` or `/reset`                                                               |
| Change model                   | `/model [provider:model]`                     | `/model [provider:model]`                                                        |
| Set a personality              | `/personality [name]`                         | `/personality [name]`                                                            |
| Retry or undo the last turn    | `/retry`, `/undo`                             | `/retry`, `/undo`                                                                |
| Compress context / check usage | `/compress`, `/usage`, `/insights [--days N]` | `/compress`, `/usage`, `/insights [days]`                                        |
| Browse skills                  | `/skills` or `/<skill-name>`                  | `/<skill-name>`                                                                  |
| Interrupt current work         | `Ctrl+C` or send a new message                | `/stop` or send a new message                                                    |
| Platform-specific status       | `/platforms`                                  | `/status`, `/sethome`                                                            |
| Route privileged approvals     | Configure locally                            | [`/set_admin_channel`](docs/admin-approvals.md)                                  |

Run `marlow --help` for CLI commands and `marlow gateway --help` for messaging gateway commands.

---

## Documentation

- [README](README.md) — install, quick start, and command overview
- [Contributing guide](CONTRIBUTING.md) — development setup and project conventions
- [Security policy](SECURITY.md) — trust model and vulnerability reporting
- [Admin approvals](docs/admin-approvals.md) — privileged approval routing
- [Network isolation](docs/security/network-egress-isolation.md) — container egress controls

---

## Contributing

We welcome contributions! See the [Contributing Guide](CONTRIBUTING.md) for development setup, code style, and PR process.

Quick start for contributors:

```bash
git clone https://github.com/stellan-lee/Marlow.git
cd Marlow
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
scripts/run_tests.sh
```

---

## Community

- 🐛 [Issues](https://github.com/stellan-lee/Marlow/issues)
- 🔌 [computer-use-linux](https://github.com/avifenesh/computer-use-linux) — Linux desktop-control MCP server for Marlow and other MCP hosts, with AT-SPI accessibility trees, Wayland/X11 input, screenshots, and compositor window targeting.

---

## License

MIT — see [LICENSE](LICENSE).
