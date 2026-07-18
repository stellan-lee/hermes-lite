# Langfuse Observability Plugin

This plugin ships bundled with Marlow but is **opt-in** — it only loads when
you explicitly enable it.

## Enable

Pick one:

```bash
# Interactive: walks you through credentials + SDK install + enable
marlow tools  # → Langfuse Observability

# Manual
pip install langfuse
marlow plugins enable observability/langfuse
```

## Required credentials

Set these in `~/.marlow/.env` (or via `marlow tools`):

```bash
MARLOW_LANGFUSE_PUBLIC_KEY=pk-lf-...
MARLOW_LANGFUSE_SECRET_KEY=sk-lf-...
MARLOW_LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or your self-hosted URL
```

Without the SDK or credentials the hooks no-op silently — the plugin fails
open.

## Verify

```bash
marlow plugins list                 # observability/langfuse should show "enabled"
marlow chat -q "hello"              # then check Langfuse for a "Marlow turn" trace
```

## Optional tuning

```bash
MARLOW_LANGFUSE_ENV=production       # environment tag
MARLOW_LANGFUSE_RELEASE=v1.0.0       # release tag
MARLOW_LANGFUSE_SAMPLE_RATE=0.5      # sample 50% of traces
MARLOW_LANGFUSE_MAX_CHARS=12000      # max chars per field (default: 12000)
MARLOW_LANGFUSE_DEBUG=true           # verbose plugin logging
```

## Disable

```bash
marlow plugins disable observability/langfuse
```
