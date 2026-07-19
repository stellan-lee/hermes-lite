# Marlow MCP Streamable HTTP Server

Marlow can expose its messaging-conversation MCP tools as a persistent,
gateway-managed Streamable HTTP endpoint. The service is disabled by default
and requires bearer authentication whenever it is enabled.

## Configure

Add the non-secret service settings to `~/.marlow/config.yaml`:

```yaml
mcp_serve:
  enabled: true
  transport: streamable_http
  host: 127.0.0.1
  port: 8765
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

## Connect a client

Configure the client with the Streamable HTTP URL and send the token as:

```http
Authorization: Bearer replace-with-a-strong-random-token
```

For Codex, keep the secret in the client's environment and reference its name:

```bash
codex mcp add marlow \
  --url http://127.0.0.1:8765/mcp \
  --bearer-token-env-var MARLOW_MCP_BEARER_TOKEN
```

## Network security

The default host is loopback-only. To accept connections from another machine,
bind to a private interface address or `0.0.0.0` and restrict reachability with
a host firewall or private network such as Tailscale. Do not send bearer tokens
over an untrusted plain-HTTP network. Put the endpoint behind an HTTPS reverse
proxy before exposing it outside a trusted private network.

The standalone `marlow mcp serve` command remains stdio-only for compatibility
with clients that launch MCP servers as child processes.
