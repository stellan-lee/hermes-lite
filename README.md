<p align="center">
  <img src="assets/banner.png" alt="Marlow Agent" width="100%">
</p>

# Marlow Agent ☤

<p align="center">
  <a href="https://marlow-agent.nousresearch.com/docs/"><img src="https://img.shields.io/badge/Docs-marlow--agent.nousresearch.com-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="https://discord.gg/NousResearch"><img src="https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://github.com/NousResearch/marlow-agent/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
  <a href="https://nousresearch.com"><img src="https://img.shields.io/badge/Built%20by-Nous%20Research-blueviolet?style=for-the-badge" alt="Built by Nous Research"></a>
</p>

**The self-improving AI agent built by [Nous Research](https://nousresearch.com).** It's the only agent with a built-in learning loop — it creates skills from experience, improves them during use, nudges itself to persist knowledge, searches its own past conversations, and builds a deepening model of who you are across sessions. Run it on a $5 VPS, a GPU cluster, or serverless infrastructure that costs nearly nothing when idle. It's not tied to your laptop — talk to it from Telegram while it works on a cloud VM.

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
curl -fsSL https://raw.githubusercontent.com/NousResearch/marlow-agent/main/scripts/install.sh | bash
```

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

📖 **[Full documentation →](https://marlow-agent.nousresearch.com/docs/)**

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

For the full command lists, see the [CLI guide](https://marlow-agent.nousresearch.com/docs/user-guide/cli) and the [Messaging Gateway guide](https://marlow-agent.nousresearch.com/docs/user-guide/messaging).

---

## Documentation

All documentation lives at **[marlow-agent.nousresearch.com/docs](https://marlow-agent.nousresearch.com/docs/)**:

| Section                                                                                             | What's Covered                                             |
| --------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| [Quickstart](https://marlow-agent.nousresearch.com/docs/getting-started/quickstart)                 | Install → setup → first conversation in 2 minutes          |
| [CLI Usage](https://marlow-agent.nousresearch.com/docs/user-guide/cli)                              | Commands, keybindings, personalities, sessions             |
| [Configuration](https://marlow-agent.nousresearch.com/docs/user-guide/configuration)                | Config file, providers, models, all options                |
| [Messaging Gateway](https://marlow-agent.nousresearch.com/docs/user-guide/messaging)                | Telegram, Discord, Slack, Feishu, Email, signed webhooks   |
| [Security](https://marlow-agent.nousresearch.com/docs/user-guide/security)                          | Command approval, DM pairing, container isolation          |
| [Tools & Toolsets](https://marlow-agent.nousresearch.com/docs/user-guide/features/tools)            | 40+ tools, toolset system, terminal backends               |
| [Skills System](https://marlow-agent.nousresearch.com/docs/user-guide/features/skills)              | Local procedural memory and skill creation                 |
| [Memory](https://marlow-agent.nousresearch.com/docs/user-guide/features/memory)                     | Persistent memory, user profiles, best practices           |
| [MCP Integration](https://marlow-agent.nousresearch.com/docs/user-guide/features/mcp)               | Connect any MCP server for extended capabilities           |
| [Cron Scheduling](https://marlow-agent.nousresearch.com/docs/user-guide/features/cron)              | Scheduled tasks with platform delivery                     |
| [Context Files](https://marlow-agent.nousresearch.com/docs/user-guide/features/context-files)       | Project context that shapes every conversation             |
| [Architecture](https://marlow-agent.nousresearch.com/docs/developer-guide/architecture)             | Project structure, agent loop, key classes                 |
| [Contributing](https://marlow-agent.nousresearch.com/docs/developer-guide/contributing)             | Development setup, PR process, code style                  |
| [CLI Reference](https://marlow-agent.nousresearch.com/docs/reference/cli-commands)                  | All commands and flags                                     |
| [Environment Variables](https://marlow-agent.nousresearch.com/docs/reference/environment-variables) | Complete env var reference                                 |

---

## Contributing

We welcome contributions! See the [Contributing Guide](https://marlow-agent.nousresearch.com/docs/developer-guide/contributing) for development setup, code style, and PR process.

Quick start for contributors — clone and go with `setup-marlow.sh`:

```bash
git clone https://github.com/NousResearch/marlow-agent.git
cd marlow-agent
./setup-marlow.sh     # installs uv, creates venv, installs .[all], symlinks ~/.local/bin/marlow
./marlow              # auto-detects the venv, no need to `source` first
```

Manual path (equivalent to the above):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
scripts/run_tests.sh
```

---

## Community

- 💬 [Discord](https://discord.gg/NousResearch)
- 🐛 [Issues](https://github.com/NousResearch/marlow-agent/issues)
- 🔌 [computer-use-linux](https://github.com/avifenesh/computer-use-linux) — Linux desktop-control MCP server for Marlow and other MCP hosts, with AT-SPI accessibility trees, Wayland/X11 input, screenshots, and compositor window targeting.
- 🔌 [MarlowClaw](https://github.com/AaronWong1999/marlowclaw) — Community WeChat bridge: Run Marlow Agent and OpenClaw on the same WeChat account.

---

## License

MIT — see [LICENSE](LICENSE).

Built by [Nous Research](https://nousresearch.com).
