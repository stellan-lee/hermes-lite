# Marlow MCP Streamable HTTP Server

Marlow can expose its messaging-conversation MCP tools as a persistent,
gateway-managed Streamable HTTP endpoint. The service is disabled by default
and supports either a fixed bearer token or a built-in single-user OAuth 2.1
flow for ChatGPT.

## Configure

Add the non-secret service settings to `~/.marlow/config.yaml`:

```yaml
mcp_serve:
  enabled: true
  transport: streamable_http
  host: 127.0.0.1
  port: 8765
  auth: bearer
```

Add a strong bearer token to `~/.marlow/.env`:

```bash
MARLOW_MCP_BEARER_TOKEN=replace-with-a-strong-random-token
```

Restart the gateway to apply the configuration:

```bash
marlow gateway restart
```

The MCP endpoint is then available at `http://127.0.0.1:8765/mcp`.

## ChatGPT OAuth

ChatGPT requires an HTTPS MCP URL and an OAuth 2.1 authorization-code flow.
Expose the local listener through an HTTPS reverse proxy or secure tunnel, then
configure its canonical public origin:

```yaml
mcp_serve:
  enabled: true
  transport: streamable_http
  host: 127.0.0.1
  port: 8765
  auth: oauth
  public_url: https://marlow.example.com
```

Set a strong owner password in `~/.marlow/.env`:

```bash
MARLOW_MCP_OAUTH_PASSWORD=replace-with-a-long-random-password
```

Generate one with `openssl rand -hex 32`, then restart the gateway. In ChatGPT,
enable developer mode, create a developer-mode app, and use:

```text
https://marlow.example.com/mcp
```

ChatGPT discovers Marlow's protected-resource and authorization-server
metadata, dynamically registers a public client, and opens Marlow's approval
page. Enter the owner password to grant the `marlow:mcp` scope. Marlow requires
PKCE `S256`, issues one-hour access tokens, rotates 30-day refresh tokens, and
stores only token hashes in `~/.marlow/mcp-oauth.db`.

See OpenAI's current
[authentication requirements](https://developers.openai.com/apps-sdk/build/auth)
and [ChatGPT connection guide](https://developers.openai.com/apps-sdk/deploy/connect-chatgpt).

## Connect a client

Configure the client with the Streamable HTTP URL and send the token as:

```http
Authorization: Bearer replace-with-a-strong-random-token
```

For Codex with bearer mode, keep the secret in the client's environment and
reference its name:

```bash
codex mcp add marlow \
  --url http://127.0.0.1:8765/mcp \
  --bearer-token-env-var MARLOW_MCP_BEARER_TOKEN
```

## Network security

The default host is loopback-only. Keep it on loopback when an HTTPS reverse
proxy or tunnel runs on the same machine. To accept direct connections from
another machine, bind to a private interface address or `0.0.0.0` and restrict
reachability with a host firewall or private network such as Tailscale. Do not
send bearer tokens over an untrusted plain-HTTP network.

OAuth mode intentionally refuses non-HTTPS public URLs. The proxy must forward
`/mcp`, `/authorize`, `/token`, `/register`, `/revoke`, `/oauth/consent`, and
both `/.well-known/` metadata paths to the local Marlow listener.

The standalone `marlow mcp serve` command remains stdio-only for compatibility
with clients that launch MCP servers as child processes.
