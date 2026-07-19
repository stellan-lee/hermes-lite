"""End-to-end coverage for ChatGPT-compatible Marlow MCP OAuth."""

import base64
import hashlib
import socket
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest


PUBLIC_URL = "https://marlow.example"
RESOURCE_URL = f"{PUBLIC_URL}/mcp"
OWNER_PASSWORD = "correct-horse-battery-staple"
REQUIRED_MESSAGING_TOOLS = {
    "conversations_list",
    "messages_read",
    "messages_send",
    "permissions_respond",
}


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _local_base(service) -> str:
    return service.endpoint.removesuffix("/mcp")


async def _register_client(httpx, local_base: str) -> str:
    response = await httpx.post(
        f"{local_base}/register",
        json={
            "redirect_uris": ["https://client.example/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "marlow:mcp",
            "client_name": "ChatGPT test client",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in payload
    return payload["client_id"]


async def _authorize(httpx, local_base: str, client_id: str, verifier: str) -> str:
    response = await httpx.get(
        f"{local_base}/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "https://client.example/callback",
            "response_type": "code",
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
            "state": "state-123",
            "scope": "marlow:mcp",
            "resource": RESOURCE_URL,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    consent_url = urlparse(response.headers["location"])
    assert f"{consent_url.scheme}://{consent_url.netloc}" == PUBLIC_URL
    return parse_qs(consent_url.query)["request_id"][0]


async def _approve(httpx, local_base: str, request_id: str) -> str:
    page = await httpx.get(
        f"{local_base}/oauth/consent", params={"request_id": request_id}
    )
    assert page.status_code == 200
    assert "ChatGPT test client" in page.text

    wrong = await httpx.post(
        f"{local_base}/oauth/consent",
        data={
            "request_id": request_id,
            "password": "wrong-password",
            "action": "approve",
        },
        follow_redirects=False,
    )
    assert wrong.status_code == 401

    approved = await httpx.post(
        f"{local_base}/oauth/consent",
        data={
            "request_id": request_id,
            "password": OWNER_PASSWORD,
            "action": "approve",
        },
        follow_redirects=False,
    )
    assert approved.status_code == 303, approved.text
    callback = urlparse(approved.headers["location"])
    callback_params = parse_qs(callback.query)
    assert callback_params["state"] == ["state-123"]
    return callback_params["code"][0]


async def _exchange_code(
    httpx,
    local_base: str,
    client_id: str,
    code: str,
    verifier: str,
) -> dict:
    response = await httpx.post(
        f"{local_base}/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": "https://client.example/callback",
            "code_verifier": verifier,
            "resource": RESOURCE_URL,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_oauth_mode_validates_required_secrets(tmp_path):
    pytest.importorskip("mcp")
    from mcp_serve import ManagedMCPHTTPServer

    with pytest.raises(ValueError, match="public_url"):
        ManagedMCPHTTPServer(
            host="127.0.0.1",
            port=8765,
            auth_mode="oauth",
            oauth_password=OWNER_PASSWORD,
            oauth_database_path=tmp_path / "oauth.db",
        )

    with pytest.raises(ValueError, match="at least 16"):
        ManagedMCPHTTPServer(
            host="127.0.0.1",
            port=8765,
            auth_mode="oauth",
            public_url=PUBLIC_URL,
            oauth_password="too-short",
            oauth_database_path=tmp_path / "oauth.db",
        )


@pytest.mark.asyncio
async def test_chatgpt_oauth_flow_and_persistence(tmp_path: Path):
    pytest.importorskip("mcp")
    httpx = pytest.importorskip("httpx")
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp_serve import ManagedMCPHTTPServer

    database_path = tmp_path / "mcp-oauth.db"
    port = _unused_local_port()
    service = ManagedMCPHTTPServer(
        host="127.0.0.1",
        port=port,
        auth_mode="oauth",
        public_url=PUBLIC_URL,
        oauth_password=OWNER_PASSWORD,
        oauth_database_path=database_path,
    )
    service.start()
    local_base = _local_base(service)

    async with httpx.AsyncClient() as client:
        try:
            discovery = await client.get(
                f"{local_base}/.well-known/oauth-authorization-server"
            )
            assert discovery.status_code == 200
            assert discovery.json()["token_endpoint_auth_methods_supported"] == ["none"]
            assert discovery.json()["code_challenge_methods_supported"] == ["S256"]

            oversized_registration = await client.post(
                f"{local_base}/register",
                content=b"{" + (b"x" * (32 * 1024)),
                headers={"Content-Type": "application/json"},
            )
            assert oversized_registration.status_code == 413

            untrusted_host = await client.get(
                f"{local_base}/.well-known/oauth-authorization-server",
                headers={"Host": "evil.example"},
            )
            assert untrusted_host.status_code == 400

            resource = await client.get(
                f"{local_base}/.well-known/oauth-protected-resource/mcp"
            )
            assert resource.status_code == 200
            assert resource.json()["resource"] == RESOURCE_URL

            unauthenticated = await client.post(
                service.endpoint,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "oauth-test", "version": "1"},
                    },
                },
                headers={"Accept": "application/json, text/event-stream"},
            )
            assert unauthenticated.status_code == 401
            assert (
                "oauth-protected-resource/mcp"
                in unauthenticated.headers["www-authenticate"]
            )

            proxied = await client.post(
                service.endpoint,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "oauth-test", "version": "1"},
                    },
                },
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Host": "marlow.example",
                },
            )
            assert proxied.status_code == 401

            client_id = await _register_client(client, local_base)
            verifier = "a" * 64
            request_id = await _authorize(client, local_base, client_id, verifier)
            code = await _approve(client, local_base, request_id)

            wrong_resource = await client.post(
                f"{local_base}/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "code": code,
                    "redirect_uri": "https://client.example/callback",
                    "code_verifier": verifier,
                    "resource": "https://wrong.example/mcp",
                },
            )
            assert wrong_resource.status_code == 400
            assert wrong_resource.json()["error"] == "invalid_target"

            wrong_pkce = await client.post(
                f"{local_base}/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "code": code,
                    "redirect_uri": "https://client.example/callback",
                    "code_verifier": "b" * 64,
                    "resource": RESOURCE_URL,
                },
            )
            assert wrong_pkce.status_code == 400
            assert wrong_pkce.json()["error"] == "invalid_grant"

            tokens = await _exchange_code(client, local_base, client_id, code, verifier)
            assert tokens["scope"] == "marlow:mcp"
            assert tokens["refresh_token"]

            reused_code = await client.post(
                f"{local_base}/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "code": code,
                    "redirect_uri": "https://client.example/callback",
                    "code_verifier": verifier,
                    "resource": RESOURCE_URL,
                },
            )
            assert reused_code.status_code == 400
            assert reused_code.json()["error"] == "invalid_grant"

            authenticated = httpx.AsyncClient(
                headers={"Authorization": f"Bearer {tokens['access_token']}"}
            )
            async with authenticated:
                async with streamable_http_client(
                    service.endpoint,
                    http_client=authenticated,
                ) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} >= REQUIRED_MESSAGING_TOOLS

            refreshed_response = await client.post(
                f"{local_base}/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": tokens["refresh_token"],
                    "resource": RESOURCE_URL,
                },
            )
            assert refreshed_response.status_code == 200, refreshed_response.text
            refreshed = refreshed_response.json()
            assert refreshed["access_token"] != tokens["access_token"]
            assert refreshed["refresh_token"] != tokens["refresh_token"]

            old_access = await client.post(
                service.endpoint,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Authorization": f"Bearer {tokens['access_token']}",
                },
            )
            assert old_access.status_code == 401

            reused_refresh = await client.post(
                f"{local_base}/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": tokens["refresh_token"],
                    "resource": RESOURCE_URL,
                },
            )
            assert reused_refresh.status_code == 400
            assert reused_refresh.json()["error"] == "invalid_grant"
        finally:
            service.stop()

    assert database_path.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(database_path) as conn:
        stored_access_hashes = {
            row[0] for row in conn.execute("SELECT token_hash FROM oauth_access_tokens")
        }
        stored_refresh_hashes = {
            row[0]
            for row in conn.execute("SELECT token_hash FROM oauth_refresh_tokens")
        }
    assert (
        hashlib.sha256(refreshed["access_token"].encode()).hexdigest()
        in stored_access_hashes
    )
    assert (
        hashlib.sha256(refreshed["refresh_token"].encode()).hexdigest()
        in stored_refresh_hashes
    )
    assert refreshed["access_token"] not in stored_access_hashes
    assert refreshed["refresh_token"] not in stored_refresh_hashes

    restarted = ManagedMCPHTTPServer(
        host="127.0.0.1",
        port=port,
        auth_mode="oauth",
        public_url=PUBLIC_URL,
        oauth_password=OWNER_PASSWORD,
        oauth_database_path=database_path,
    )
    restarted.start()
    try:
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {refreshed['access_token']}"}
        ) as authenticated:
            async with streamable_http_client(
                restarted.endpoint,
                http_client=authenticated,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
        assert {tool.name for tool in tools.tools} >= REQUIRED_MESSAGING_TOOLS
    finally:
        restarted.stop()
