# Optional Skills

Official skills maintained by Nous Research that are **not activated by default**.

These skills ship with the hermes-agent repository but are not copied to
`~/.hermes/skills/` during setup. To activate one, copy its directory into
`~/.hermes/skills/` or a project-local skills directory, then configure it
with the local `hermes skills` command.

```bash
cp -R optional-skills/devops/cli ~/.hermes/skills/
hermes skills
```

## Why optional?

Some skills are useful but not broadly needed by every user:

- **Niche integrations** — specific paid services, specialized tools
- **Experimental features** — promising but not yet proven
- **Heavyweight dependencies** — require significant setup (API keys, installs)

By keeping them optional, we keep the default skill set lean while still
providing curated, tested, official skills for users who want them.
