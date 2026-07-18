# Optional Skills

Bundled skills that are **not activated by default**.

These skills ship with the marlow-agent repository but are not copied to
`~/.marlow/skills/` during setup. To activate one, copy its directory into
`~/.marlow/skills/` or a project-local skills directory, then configure it
with the local `marlow skills` command.

```bash
cp -R optional-skills/devops/cli ~/.marlow/skills/
marlow skills
```

## Why optional?

Some skills are useful but not broadly needed by every user:

- **Niche integrations** — specific paid services, specialized tools
- **Experimental features** — promising but not yet proven
- **Heavyweight dependencies** — require significant setup (API keys, installs)

By keeping them optional, we keep the default skill set lean while still
providing curated, tested, official skills for users who want them.
