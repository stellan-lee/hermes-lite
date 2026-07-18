---
name: marlow-agent
description: "Configure, extend, or contribute to Marlow Agent."
version: 2.1.0
author: Marlow Agent + Teknium
license: MIT
platforms: [linux, macos]
metadata:
  marlow:
    tags: [marlow, setup, configuration, multi-agent, spawning, cli, gateway, development]
    homepage: https://github.com/NousResearch/marlow-agent
    related_skills: [claude-code, codex, opencode]
---

# Marlow Agent

Marlow Agent is an open-source AI agent framework by Nous Research that runs in your terminal and messaging platforms. It provides autonomous coding and task execution through tool calling, using Codex OAuth or a custom/local OpenAI-compatible endpoint on Linux and macOS.

What makes Marlow different:

- **Self-improving through skills** — Marlow learns from experience by saving reusable procedures as skills. When it solves a complex problem, discovers a workflow, or gets corrected, it can persist that knowledge as a skill document that loads into future sessions. Skills accumulate over time, making the agent better at your specific tasks and environment.
- **Persistent memory across sessions** — remembers who you are, your preferences, environment details, and lessons learned through local memory, Holographic memory, or Honcho.
- **Multi-platform gateway** — the same agent runs on Telegram, Discord, Slack, Feishu/Lark, Email, and signed webhooks with full tool access.
- **Flexible inference** — use Codex OAuth or point Marlow at Ollama, vLLM, LM Studio, or another custom OpenAI-compatible endpoint.
- **Profiles** — run multiple independent Marlow instances with isolated configs, sessions, skills, and memory.
- **Extensible** — plugins, MCP servers, custom tools, webhook triggers, cron scheduling, and the full Python ecosystem.

People use Marlow for software development, research, system administration, data analysis, content creation, home automation, and anything else that benefits from an AI agent with persistent context and full system access.

**This skill helps you work with Marlow Agent effectively** — setting it up, configuring features, spawning additional agent instances, troubleshooting issues, finding the right commands and settings, and understanding how the system works when you need to extend or contribute to it.

**Docs:** https://marlow-agent.nousresearch.com/docs/

## Quick Start

```bash
# Install
curl -fsSL https://raw.githubusercontent.com/NousResearch/marlow-agent/main/scripts/install.sh | bash

# Interactive chat (default)
marlow

# Single query
marlow chat -q "What is the capital of France?"

# Setup wizard
marlow setup

# Change model/provider
marlow model

# Check health
marlow doctor
```

---

## CLI Reference

### Global Flags

```
marlow [flags] [command]

  --version, -V             Show version
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --pass-session-id         Include session ID in system prompt
```

No subcommand defaults to `chat`.

### Chat

```
marlow chat [flags]
  -q, --query TEXT          Single query, non-interactive
  -m, --model MODEL         Codex or custom endpoint model id
  -t, --toolsets LIST       Comma-separated toolsets
  --provider PROVIDER       Force provider (openai-codex or custom)
  -v, --verbose             Verbose output
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --source TAG              Session source tag (default: cli)
```

### Configuration

```
marlow setup [section]      Interactive wizard (model|terminal|gateway|tools|agent)
marlow model                Interactive model/provider picker
marlow config               View current config
marlow config edit          Open config.yaml in $EDITOR
marlow config set KEY VAL   Set a config value
marlow config path          Print config.yaml path
marlow config env-path      Print .env path
marlow config check         Check for missing/outdated config
marlow config migrate       Update config with new options
marlow login                Authenticate with OpenAI Codex
marlow logout               Clear Codex authentication
marlow doctor [--fix]       Check dependencies and config
marlow status [--all]       Show component status
```

### Tools & Skills

```
marlow tools                Interactive tool enable/disable (curses UI)
marlow tools list           Show all tools and status
marlow tools enable NAME    Enable a toolset
marlow tools disable NAME   Disable a toolset

marlow skills               Enable or disable installed local skills
# Add skills by placing SKILL.md packages under ~/.marlow/skills/
```

### MCP Servers

```
marlow mcp serve            Run Marlow as an MCP server
marlow mcp add NAME         Add an MCP server (--url or --command)
marlow mcp remove NAME      Remove an MCP server
marlow mcp list             List configured servers
marlow mcp test NAME        Test connection
marlow mcp configure NAME   Toggle tool selection
```

### Gateway (Messaging Platforms)

```
marlow gateway run          Start gateway foreground
marlow gateway install      Install as background service
marlow gateway start/stop   Control the service
marlow gateway restart      Restart the service
marlow gateway status       Check status
marlow gateway setup        Configure platforms
```

Supported platforms: Telegram, Discord, Slack, Feishu/Lark, Email, and signed webhooks.

Platform docs: https://marlow-agent.nousresearch.com/docs/user-guide/messaging/

### Sessions

```
marlow sessions list        List recent sessions
marlow sessions browse      Interactive picker
marlow sessions export OUT  Export to JSONL
marlow sessions rename ID T Rename a session
marlow sessions delete ID   Delete a session
marlow sessions prune       Clean up old sessions (--older-than N days)
marlow sessions stats       Session store statistics
```

### Cron Jobs

```
marlow cron list            List jobs (--all for disabled)
marlow cron create SCHED    Create: '30m', 'every 2h', '0 9 * * *'
marlow cron edit ID         Edit schedule, prompt, delivery
marlow cron pause/resume ID Control job state
marlow cron run ID          Trigger on next tick
marlow cron remove ID       Delete a job
marlow cron status          Scheduler status
```

### Webhooks

```
marlow webhook subscribe N  Create route at /webhooks/<name>
marlow webhook list         List subscriptions
marlow webhook remove NAME  Remove a subscription
marlow webhook test NAME    Send a test POST
```

### Profiles

```
marlow profile list         List all profiles
marlow profile create NAME  Create (--clone, --clone-all, --clone-from)
marlow profile use NAME     Set sticky default
marlow profile delete NAME  Delete a profile
marlow profile show NAME    Show details
marlow profile alias NAME   Manage wrapper scripts
marlow profile rename A B   Rename a profile
marlow profile export NAME  Export to tar.gz
marlow profile import FILE  Import from archive
```

### Other

```
marlow insights [--days N]  Usage analytics
marlow update               Update to latest version
marlow pairing list/approve/revoke  DM authorization
marlow plugins list/install/remove  Plugin management
marlow honcho setup/status  Honcho memory integration (requires honcho plugin)
marlow memory setup/status/off  Memory provider config
marlow completion bash|zsh  Shell completions
marlow uninstall            Uninstall Marlow
```

---

## Slash Commands (In-Session)

Type these during an interactive chat session. New commands land fairly
often; if something below looks stale, run `/help` in-session for the
authoritative list or see the [live slash commands reference](https://marlow-agent.nousresearch.com/docs/reference/slash-commands).
The registry of record is `marlow_cli/commands.py` — every consumer
(autocomplete, Telegram menu, Slack mapping, `/help`) derives from it.

### Session Control
```
/new (/reset)        Fresh session
/clear               Clear screen + new session (CLI)
/retry               Resend last message
/undo                Remove last exchange
/title [name]        Name the session
/compress            Manually compress context
/stop                Kill background processes
/rollback [N]        Restore filesystem checkpoint
/snapshot [sub]      Create or restore state snapshots of Marlow config/state (CLI)
/background <prompt> Run prompt in background
/queue <prompt>      Queue for next turn
/steer <prompt>      Inject a message after the next tool call without interrupting
/agents (/tasks)     Show active agents and running tasks
/resume [name]       Resume a named session
/goal [text|sub]     Set a standing goal Marlow works on across turns until achieved
                     (subcommands: status, pause, resume, clear)
/redraw              Force a full UI repaint (CLI)
```

### Configuration
```
/config              Show config (CLI)
/model [name]        Show or change model
/personality [name]  Set personality
/reasoning [level]   Set reasoning (none|minimal|low|medium|high|xhigh|show|hide)
/verbose             Cycle: off → new → all → verbose
/voice [on|off|tts]  Voice mode
/yolo                Toggle approval bypass
/busy [sub]          Control what Enter does while Marlow is working (CLI)
                     (subcommands: queue, steer, interrupt, status)
/indicator [style]   Pick the TUI busy-indicator style (CLI)
                     (styles: kaomoji, emoji, unicode, ascii)
/footer [on|off]     Toggle gateway runtime-metadata footer on final replies
/skin [name]         Change theme (CLI)
/statusbar           Toggle status bar (CLI)
```

### Tools & Skills
```
/tools               Manage tools (CLI)
/toolsets            List toolsets (CLI)
/skills              Search/install skills (CLI)
/skill <name>        Load a skill into session
/reload-skills       Re-scan ~/.marlow/skills/ for added/removed skills
/reload              Reload .env variables into the running session (CLI)
/reload-mcp          Reload MCP servers
/cron                Manage cron jobs (CLI)
/curator [sub]       Background skill maintenance (status, run, pin, archive, …)
/plugins             List plugins (CLI)
```

### Gateway
```
/approve             Approve a pending command (gateway)
/deny                Deny a pending command (gateway)
/restart             Restart gateway (gateway)
/sethome             Set current chat as home channel (gateway)
/update              Update Marlow to latest (gateway)
/topic [sub]         Enable or inspect Telegram DM topic sessions (gateway)
/platforms (/gateway) Show platform connection status (gateway)
```

### Utility
```
/branch (/fork)      Branch the current session
/browser             Open CDP browser connection
/history             Show conversation history (CLI)
/save                Save conversation to file (CLI)
/copy [N]            Copy the last assistant response to clipboard (CLI)
/paste               Attach clipboard image (CLI)
/image               Attach local image file (CLI)
```

### Info
```
/help                Show commands
/commands [page]     Browse all commands (gateway)
/usage               Token usage
/insights [days]     Usage analytics
/gquota              Show Google Gemini Code Assist quota usage (CLI)
/status              Session info (gateway)
/profile             Active profile info
/debug               Upload debug report (system info + logs) and get shareable links
```

### Exit
```
/quit (/exit, /q)    Exit CLI
```

---

## Key Paths & Config

```
~/.marlow/config.yaml       Main configuration
~/.marlow/.env              API keys and secrets
$MARLOW_HOME/skills/        Installed skills
~/.marlow/sessions/         Gateway routing index, request dumps, *.jsonl transcripts (and optional per-session JSON snapshots when sessions.write_json_snapshots: true)
~/.marlow/state.db          Canonical session store (SQLite + FTS5)
~/.marlow/logs/             Gateway and error logs
~/.marlow/auth.json         OAuth tokens and credential pools
~/.marlow/marlow-agent/     Source code (if git-installed)
```

Profiles use `~/.marlow/profiles/<name>/` with the same layout.

### Config Sections

Edit with `marlow config edit` or `marlow config set section.key value`.

| Section | Key options |
|---------|-------------|
| `model` | `default`, `provider`, `base_url`, `api_key`, `context_length` |
| `agent` | `max_turns` (90), `tool_use_enforcement` |
| `terminal` | `backend` (local/docker/ssh), `cwd`, `timeout` (180) |
| `compression` | `enabled`, `threshold` (0.50), `target_ratio` (0.20) |
| `display` | `skin`, `tool_progress`, `show_reasoning`, `show_cost` |
| `stt` | `enabled`, `provider` (local/groq/openai/mistral) |
| `tts` | `provider` (edge/elevenlabs/openai/minimax/mistral/neutts) |
| `memory` | `memory_enabled`, `user_profile_enabled`, `provider` |
| `security` | `tirith_enabled`, `website_blocklist` |
| `delegation` | `model`, `provider`, `base_url`, `api_key`, `max_iterations` (50), `reasoning_effort` |
| `checkpoints` | `enabled`, `max_snapshots` (50) |

Full config reference: https://marlow-agent.nousresearch.com/docs/user-guide/configuration

### Providers

Choose Codex or a custom/local endpoint with `marlow model` or `marlow setup`.

| Provider | Auth | Key env var |
|----------|------|-------------|
| OpenAI Codex | OAuth | `marlow login` |
| Custom/local endpoint | Config | `model.base_url` + `model.api_key` in config.yaml |

Full provider docs: https://marlow-agent.nousresearch.com/docs/integrations/providers

### Toolsets

Enable/disable via `marlow tools` (interactive) or `marlow tools enable/disable NAME`.

| Toolset | What it provides |
|---------|-----------------|
| `web` | Web search and content extraction |
| `search` | Web search only (subset of `web`) |
| `browser` | Local Chromium automation or an existing CDP browser |
| `terminal` | Shell commands and process management |
| `file` | File read/write/search/patch |
| `code_execution` | Sandboxed Python execution |
| `vision` | Image analysis |
| `image_gen` | AI image generation |
| `tts` | Text-to-speech |
| `skills` | Skill browsing and management |
| `memory` | Persistent cross-session memory |
| `session_search` | Search past conversations |
| `delegation` | Subagent task delegation |
| `cronjob` | Scheduled task management |
| `clarify` | Ask user clarifying questions |
| `messaging` | Cross-platform message sending |
| `todo` | In-session task planning and tracking |
| `debugging` | Extra introspection/debug tools (off by default) |
| `safe` | Minimal, low-risk toolset for locked-down sessions |
| `discord` | Discord integration tools |
| `discord_admin` | Discord admin/moderation tools |
| `feishu_doc` | Feishu (Lark) document tools |
| `feishu_drive` | Feishu (Lark) drive tools |
| `rl` | Reinforcement learning tools (off by default) |
| `moa` | Mixture of Agents (off by default) |

Full enumeration lives in `toolsets.py` as the `TOOLSETS` dict; `_MARLOW_CORE_TOOLS` is the default bundle most platforms inherit from.

Tool changes take effect on `/reset` (new session). They do NOT apply mid-conversation to preserve prompt caching.

---

## Security & Privacy Toggles

Common "why is Marlow doing X to my output / tool calls / commands?" toggles — and the exact commands to change them. Most of these need a fresh session (`/reset` in chat, or start a new `marlow` invocation) because they're read once at startup.

### Secret redaction in tool output

Secret redaction is **on by default** — tool output (terminal stdout, `read_file`, web content, subagent summaries, etc.) is scanned for strings that look like API keys, tokens, and secrets before it enters the conversation context and logs. Leave it enabled for normal use:

```bash
marlow config set security.redact_secrets true       # keep enabled globally
```

**Restart required.** `security.redact_secrets` is snapshotted at import time — toggling it mid-session (e.g. via `export MARLOW_REDACT_SECRETS=false` from a tool call) will NOT take effect for the running process. Tell the user to change it in config from a terminal, then start a new session. This is deliberate — it prevents an LLM from flipping the toggle on itself mid-task.

Disable only when you deliberately need raw credential-like strings for debugging or redactor development:
```bash
marlow config set security.redact_secrets false
```

### PII redaction in gateway messages

Separate from secret redaction. When enabled, the gateway hashes user IDs and strips phone numbers from the session context before it reaches the model:

```bash
marlow config set privacy.redact_pii true    # enable
marlow config set privacy.redact_pii false   # disable (default)
```

### Command approval prompts

By default (`approvals.mode: manual`), Marlow prompts the user before running shell commands flagged as destructive (`rm -rf`, `git reset --hard`, etc.). The modes are:

- `manual` — always prompt (default)
- `smart` — use an auxiliary LLM to auto-approve low-risk commands, prompt on high-risk
- `off` — skip all approval prompts (equivalent to `--yolo`)

```bash
marlow config set approvals.mode smart       # recommended middle ground
marlow config set approvals.mode off         # bypass everything (not recommended)
```

Per-invocation bypass without changing config:
- `marlow --yolo …`
- `export MARLOW_YOLO_MODE=1`

Note: YOLO / `approvals.mode: off` does NOT turn off secret redaction. They are independent.

### Shell hooks allowlist

Some shell-hook integrations require explicit allowlisting before they fire. Managed via `~/.marlow/shell-hooks-allowlist.json` — prompted interactively the first time a hook wants to run.

### Disabling the web/browser/image-gen tools

To keep the model away from network or media tools entirely, open `marlow tools` and toggle per-platform. Takes effect on next session (`/reset`). See the Tools & Skills section above.

---

## Voice & Transcription

### STT (Voice → Text)

Voice messages from messaging platforms are auto-transcribed.

Provider priority (auto-detected):
1. **Local faster-whisper** — free, no API key: `pip install faster-whisper`
2. **Groq Whisper** — free tier: set `GROQ_API_KEY`
3. **OpenAI Whisper** — paid: set `VOICE_TOOLS_OPENAI_KEY`
4. **Mistral Voxtral** — set `MISTRAL_API_KEY`

Config:
```yaml
stt:
  enabled: true
  provider: local        # local, groq, openai, mistral
  local:
    model: base          # tiny, base, small, medium, large-v3
```

### TTS (Text → Voice)

| Provider | Env var | Free? |
|----------|---------|-------|
| Edge TTS | None | Yes (default) |
| ElevenLabs | `ELEVENLABS_API_KEY` | Free tier |
| OpenAI | `VOICE_TOOLS_OPENAI_KEY` | Paid |
| MiniMax | `MINIMAX_API_KEY` | Paid |
| Mistral (Voxtral) | `MISTRAL_API_KEY` | Paid |
| NeuTTS (local) | None (`pip install neutts[all]` + `espeak-ng`) | Free |

Voice commands: `/voice on` (voice-to-voice), `/voice tts` (always voice), `/voice off`.

---

## Spawning Additional Marlow Instances

Run additional Marlow processes as fully independent subprocesses — separate sessions, tools, and environments.

### When to Use This vs delegate_task

| | `delegate_task` | Spawning `marlow` process |
|-|-----------------|--------------------------|
| Isolation | Separate conversation, shared process | Fully independent process |
| Duration | Minutes (bounded by parent loop) | Hours/days |
| Tool access | Subset of parent's tools | Full tool access |
| Interactive | No | Yes (PTY mode) |
| Use case | Quick parallel subtasks | Long autonomous missions |

### One-Shot Mode

```
terminal(command="marlow chat -q 'Research GRPO papers and write summary to ~/research/grpo.md'", timeout=300)

# Background for long tasks:
terminal(command="marlow chat -q 'Set up CI/CD for ~/myapp'", background=true)
```

### Interactive PTY Mode (via tmux)

Marlow uses prompt_toolkit, which requires a real terminal. Use tmux for interactive spawning:

```
# Start
terminal(command="tmux new-session -d -s agent1 -x 120 -y 40 'marlow'", timeout=10)

# Wait for startup, then send a message
terminal(command="sleep 8 && tmux send-keys -t agent1 'Build a FastAPI auth service' Enter", timeout=15)

# Read output
terminal(command="sleep 20 && tmux capture-pane -t agent1 -p", timeout=5)

# Send follow-up
terminal(command="tmux send-keys -t agent1 'Add rate limiting middleware' Enter", timeout=5)

# Exit
terminal(command="tmux send-keys -t agent1 '/exit' Enter && sleep 2 && tmux kill-session -t agent1", timeout=10)
```

### Multi-Agent Coordination

```
# Agent A: backend
terminal(command="tmux new-session -d -s backend -x 120 -y 40 'marlow -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t backend 'Build REST API for user management' Enter", timeout=15)

# Agent B: frontend
terminal(command="tmux new-session -d -s frontend -x 120 -y 40 'marlow -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t frontend 'Build React dashboard for user management' Enter", timeout=15)

# Check progress, relay context between them
terminal(command="tmux capture-pane -t backend -p | tail -30", timeout=5)
terminal(command="tmux send-keys -t frontend 'Here is the API schema from the backend agent: ...' Enter", timeout=5)
```

### Session Resume

```
# Resume most recent session
terminal(command="tmux new-session -d -s resumed 'marlow --continue'", timeout=10)

# Resume specific session
terminal(command="tmux new-session -d -s resumed 'marlow --resume 20260225_143052_a1b2c3'", timeout=10)
```

### Tips

- **Prefer `delegate_task` for quick subtasks** — less overhead than spawning a full process
- **Use `-w` (worktree mode)** when spawning agents that edit code — prevents git conflicts
- **Set timeouts** for one-shot mode — complex tasks can take 5-10 minutes
- **Use `marlow chat -q` for fire-and-forget** — no PTY needed
- **Use tmux for interactive sessions** — raw PTY mode has `\r` vs `\n` issues with prompt_toolkit
- **For scheduled tasks**, use the `cronjob` tool instead of spawning — handles delivery and retry

---

## Durable & Background Systems

Four systems run alongside the main conversation loop. Quick reference
here; full developer notes live in `AGENTS.md`, user-facing docs under
https://marlow-agent.nousresearch.com/docs/user-guide/features/

### Delegation (`delegate_task`)

Synchronous subagent spawn — the parent waits for the child's summary
before continuing its own loop. Isolated context + terminal session.

- **Single:** `delegate_task(goal, context, toolsets)`.
- **Batch:** `delegate_task(tasks=[{goal, ...}, ...])` runs children in
  parallel, capped by `delegation.max_concurrent_children` (default 3).
- **Roles:** `leaf` (default; cannot re-delegate) vs `orchestrator`
  (can spawn its own workers, bounded by `delegation.max_spawn_depth`).
- **Not durable.** If the parent is interrupted, the child is
  cancelled. For work that must outlive the turn, use `cronjob` or
  `terminal(background=True, notify_on_complete=True)`.

Config: `delegation.*` in `config.yaml`.

### Cron (scheduled jobs)

Durable scheduler — `cron/jobs.py` + `cron/scheduler.py`. Drive it via
the `cronjob` tool, the `marlow cron` CLI (`list`, `add`, `edit`,
`pause`, `resume`, `run`, `remove`), or the `/cron` slash command.

- **Schedules:** duration (`"30m"`, `"2h"`), "every" phrase
  (`"every monday 9am"`), 5-field cron (`"0 9 * * *"`), or ISO timestamp.
- **Per-job knobs:** `skills`, `model`/`provider` override, `script`
  (pre-run data collection; `no_agent=True` makes the script the whole
  job), `context_from` (chain job A's output into job B), `workdir`
  (run in a specific dir with its `AGENTS.md` / `CLAUDE.md` loaded),
  multi-platform delivery.
- **Invariants:** 3-minute hard interrupt per run, `.tick.lock` file
  prevents duplicate ticks across processes, cron sessions pass
  `skip_memory=True` by default, and cron deliveries are framed with a
  header/footer instead of being mirrored into the target gateway
  session (keeps role alternation intact).

User docs: https://marlow-agent.nousresearch.com/docs/user-guide/features/cron

### Curator (skill lifecycle)

Background maintenance for agent-created skills. Tracks usage, marks
idle skills stale, archives stale ones, keeps a pre-run tar.gz backup
so nothing is lost.

- **CLI:** `marlow curator <verb>` — `status`, `run`, `pause`, `resume`,
  `pin`, `unpin`, `archive`, `restore`, `prune`, `backup`, `rollback`.
- **Slash:** `/curator <subcommand>` mirrors the CLI.
- **Scope:** only touches skills with `created_by: "agent"` provenance.
  Bundled and manually installed local skills are off-limits. **Never deletes** —
  max destructive action is archive. Pinned skills are exempt from
  every auto-transition and every LLM review pass.
- **Telemetry:** sidecar at `~/.marlow/skills/.usage.json` holds
  per-skill `use_count`, `view_count`, `patch_count`,
  `last_activity_at`, `state`, `pinned`.

Config: `curator.*` (`enabled`, `interval_hours`, `min_idle_hours`,
`stale_after_days`, `archive_after_days`, `backup.*`).
User docs: https://marlow-agent.nousresearch.com/docs/user-guide/features/curator

## Troubleshooting

### Voice not working
1. Check `stt.enabled: true` in config.yaml
2. Verify provider: `pip install faster-whisper` or set API key
3. In gateway: `/restart`. In CLI: exit and relaunch.

### Tool not available
1. `marlow tools` — check if toolset is enabled for your platform
2. Some tools need env vars (check `.env`)
3. `/reset` after enabling tools

### Model/provider issues
1. `marlow doctor` — check config and dependencies
2. `marlow login` — re-authenticate Codex OAuth
3. Check `.env` has the right API key

### Changes not taking effect
- **Tools/skills:** `/reset` starts a new session with updated toolset
- **Config changes:** In gateway: `/restart`. In CLI: exit and relaunch.
- **Code changes:** Restart the CLI or gateway process

### Skills not showing
1. `marlow skills` — verify local skill configuration
2. `marlow skills config` — check platform enablement
3. Load explicitly: `/skill name` or `marlow -s name`

### Gateway issues
Check logs first:
```bash
grep -i "failed to send\|error" ~/.marlow/logs/gateway.log | tail -20
```

Common gateway problems:
- **Gateway dies on SSH logout**: Enable linger: `sudo loginctl enable-linger $USER`
- **Gateway crash loop**: Reset the failed state: `systemctl --user reset-failed marlow-gateway`

### Platform-specific issues
- **Discord bot silent**: Must enable **Message Content Intent** in Bot → Privileged Gateway Intents.
- **Slack bot only works in DMs**: Must subscribe to `message.channels` event. Without it, the bot ignores public channels.

### Auxiliary models not working
If `auxiliary` tasks (vision, compression, session_search) fail silently, the `auto` provider can't find a backend. Either set `OPENROUTER_API_KEY` or `GOOGLE_API_KEY`, or explicitly configure each auxiliary task's provider:
```bash
marlow config set auxiliary.vision.provider <your_provider>
marlow config set auxiliary.vision.model <model_name>
```

---

## Where to Find Things

| Looking for... | Location |
|----------------|----------|
| Config options | `marlow config edit` or [Configuration docs](https://marlow-agent.nousresearch.com/docs/user-guide/configuration) |
| Available tools | `marlow tools list` or [Tools reference](https://marlow-agent.nousresearch.com/docs/reference/tools-reference) |
| Slash commands | `/help` in session or [Slash commands reference](https://marlow-agent.nousresearch.com/docs/reference/slash-commands) |
| Installed skills | `marlow skills` or `~/.marlow/skills/` |
| Provider setup | `marlow model` or [Providers guide](https://marlow-agent.nousresearch.com/docs/integrations/providers) |
| Platform setup | `marlow gateway setup` or [Messaging docs](https://marlow-agent.nousresearch.com/docs/user-guide/messaging/) |
| MCP servers | `marlow mcp list` or [MCP guide](https://marlow-agent.nousresearch.com/docs/user-guide/features/mcp) |
| Profiles | `marlow profile list` or [Profiles docs](https://marlow-agent.nousresearch.com/docs/user-guide/profiles) |
| Cron jobs | `marlow cron list` or [Cron docs](https://marlow-agent.nousresearch.com/docs/user-guide/features/cron) |
| Memory | `marlow memory status` or [Memory docs](https://marlow-agent.nousresearch.com/docs/user-guide/features/memory) |
| Env variables | `marlow config env-path` or [Env vars reference](https://marlow-agent.nousresearch.com/docs/reference/environment-variables) |
| CLI commands | `marlow --help` or [CLI reference](https://marlow-agent.nousresearch.com/docs/reference/cli-commands) |
| Gateway logs | `~/.marlow/logs/gateway.log` |
| Session files | `marlow sessions browse` (reads state.db) |
| Source code | `~/.marlow/marlow-agent/` |

---

## Contributor Quick Reference

For occasional contributors and PR authors. Full developer docs: https://marlow-agent.nousresearch.com/docs/developer-guide/

### Project Layout

```
marlow-agent/
├── run_agent.py          # AIAgent — core conversation loop
├── model_tools.py        # Tool discovery and dispatch
├── toolsets.py           # Toolset definitions
├── cli.py                # Interactive CLI (MarlowCLI)
├── marlow_state.py       # SQLite session store
├── agent/                # Prompt builder, context compression, memory, model routing, credential pooling, skill dispatch
├── marlow_cli/           # CLI subcommands, config, setup, commands
│   ├── commands.py       # Slash command registry (CommandDef)
│   ├── config.py         # DEFAULT_CONFIG, env var definitions
│   └── main.py           # CLI entry point and argparse
├── tools/                # One file per tool
│   └── registry.py       # Central tool registry
├── gateway/              # Messaging gateway
│   └── platforms/        # Platform adapters (telegram, discord, etc.)
├── cron/                 # Job scheduler
└── tests/                # ~3000 pytest tests
```

Config: `~/.marlow/config.yaml` (settings), `~/.marlow/.env` (API keys).

### Adding a Tool (3 files)

**1. Create `tools/your_tool.py`:**
```python
import json, os
from tools.registry import registry

def check_requirements() -> bool:
    return bool(os.getenv("EXAMPLE_API_KEY"))

def example_tool(param: str, task_id: str = None) -> str:
    return json.dumps({"success": True, "data": "..."})

registry.register(
    name="example_tool",
    toolset="example",
    schema={"name": "example_tool", "description": "...", "parameters": {...}},
    handler=lambda args, **kw: example_tool(
        param=args.get("param", ""), task_id=kw.get("task_id")),
    check_fn=check_requirements,
    requires_env=["EXAMPLE_API_KEY"],
)
```

**2. Add to `toolsets.py`** → `_MARLOW_CORE_TOOLS` list.

Auto-discovery: any `tools/*.py` file with a top-level `registry.register()` call is imported automatically — no manual list needed.

All handlers must return JSON strings. Use `get_marlow_home()` for paths, never hardcode `~/.marlow`.

### Adding a Slash Command

1. Add `CommandDef` to `COMMAND_REGISTRY` in `marlow_cli/commands.py`
2. Add handler in `cli.py` → `process_command()`
3. (Optional) Add gateway handler in `gateway/run.py`

All consumers (help text, autocomplete, Telegram menu, Slack mapping) derive from the central registry automatically.

### Agent Loop (High Level)

```
run_conversation():
  1. Build system prompt
  2. Loop while iterations < max:
     a. Call LLM (OpenAI-format messages + tool schemas)
     b. If tool_calls → dispatch each via handle_function_call() → append results → continue
     c. If text response → return
  3. Context compression triggers automatically near token limit
```

### Testing

```bash
python -m pytest tests/ -o 'addopts=' -q   # Full suite
python -m pytest tests/tools/ -q            # Specific area
```

- Tests auto-redirect `MARLOW_HOME` to temp dirs — never touch real `~/.marlow/`
- Run full suite before pushing any change
- Use `-o 'addopts='` to clear any baked-in pytest flags

### Extending the system prompt's execution-environment block

Factual guidance about the host OS, user home, cwd, terminal backend, and shell is emitted from `agent/prompt_builder.py::build_environment_hints()`. The convention:

- **Local terminal backend** → emit host info (OS, `$HOME`, cwd).
- **Remote terminal backend** (`docker` or `ssh`) → **suppress** host info entirely and describe only the backend. A live `uname`/`whoami`/`pwd` probe runs inside the backend via `tools.environments.get_environment(...).execute(...)`, cached per process in `_BACKEND_PROBE_CACHE`, with a static fallback if the probe times out.
- **Key fact for prompt authoring:** when `TERMINAL_ENV != "local"`, *every* file tool (`read_file`, `write_file`, `patch`, `search_files`) runs inside the backend container, not on the host. The system prompt must never describe the host in that case — the agent can't touch it.

Full design notes, the exact emitted strings, and testing pitfalls:
`references/prompt-builder-environment-hints.md`.

### Commit Conventions

```
type: concise subject line

Optional body.
```

Types: `fix:`, `feat:`, `refactor:`, `docs:`, `chore:`

### Key Rules

- **Never break prompt caching** — don't change context, tools, or system prompt mid-conversation
- **Message role alternation** — never two assistant or two user messages in a row
- Use `get_marlow_home()` from `marlow_constants` for all paths (profile-safe)
- Config values go in `config.yaml`, secrets go in `.env`
- New tools need a `check_fn` so they only appear when requirements are met
