# Security

Report vulnerabilities privately to the repository maintainers. Do not place
secrets, exploit details, or private user data in a public issue.

## Security model

Hermes Lite is a local application running with the current user's operating
system permissions. It does not provide a process sandbox.

- Keep API keys in the environment or `~/.hermes/.env`, not `config.yaml`.
- File tools reject paths that resolve outside the configured workspace.
- Terminal commands use an argument vector without an implicit shell and ask
  for approval by default.
- Approved commands may still access any resource available to the current
  user. Disable terminal execution for untrusted models or prompts.
- Treat model output, repository content, and tool results as untrusted input.
- Review commands before approving them and use a dedicated low-privilege
  account for sensitive work.

Hermes Lite deliberately excludes remote connectors, MCP, plugins, background
workers, and hosted account services to keep the exposed surface small.
