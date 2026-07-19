"""Tests for the gateway-managed MCP Streamable HTTP service."""

import asyncio
import json
import socket
from unittest.mock import AsyncMock

import pytest

from gateway.config import GatewayConfig, MCPServeConfig
from gateway.run import GatewayRunner


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class TestMCPServeConfig:
    def test_cli_defaults_and_secret_metadata(self):
        from marlow_cli.config import DEFAULT_CONFIG, OPTIONAL_ENV_VARS

        assert DEFAULT_CONFIG["mcp_serve"] == {
            "enabled": False,
            "transport": "streamable_http",
            "host": "127.0.0.1",
            "port": 8765,
            "auth": "bearer",
            "public_url": None,
        }
        assert OPTIONAL_ENV_VARS["MARLOW_MCP_BEARER_TOKEN"]["password"] is True
        assert OPTIONAL_ENV_VARS["MARLOW_MCP_OAUTH_PASSWORD"]["password"] is True

    def test_defaults_are_disabled_and_loopback_only(self):
        config = MCPServeConfig.from_dict(None)

        assert config.enabled is False
        assert config.transport == "streamable_http"
        assert config.host == "127.0.0.1"
        assert config.port == 8765
        assert config.auth == "bearer"
        assert config.public_url is None

    def test_enabled_streamable_http_config(self):
        config = MCPServeConfig.from_dict(
            {
                "enabled": True,
                "transport": "streamable-http",
                "host": "0.0.0.0",
                "port": "9000",
            }
        )

        assert config == MCPServeConfig(
            enabled=True,
            transport="streamable_http",
            host="0.0.0.0",
            port=9000,
        )

    @pytest.mark.parametrize("port", [0, 65536, "not-a-port"])
    def test_invalid_port_is_rejected(self, port):
        with pytest.raises(ValueError, match="mcp_serve.port"):
            MCPServeConfig.from_dict({"enabled": True, "port": port})

    def test_managed_stdio_is_rejected(self):
        with pytest.raises(ValueError, match="streamable_http"):
            MCPServeConfig.from_dict(
                {"enabled": True, "transport": "stdio"}
            )

    def test_oauth_requires_https_public_origin(self):
        with pytest.raises(ValueError, match="HTTPS origin"):
            MCPServeConfig.from_dict(
                {
                    "enabled": True,
                    "auth": "oauth",
                    "public_url": "http://office:8765",
                }
            )

    def test_oauth_public_origin(self):
        config = MCPServeConfig.from_dict(
            {
                "enabled": True,
                "auth": "oauth",
                "public_url": "https://marlow.example/",
            }
        )

        assert config.auth == "oauth"
        assert config.public_url == "https://marlow.example"

    def test_gateway_config_round_trip(self):
        original = GatewayConfig(
            mcp_serve=MCPServeConfig(
                enabled=True,
                host="127.0.0.1",
                port=9123,
            )
        )

        restored = GatewayConfig.from_dict(original.to_dict())

        assert restored.mcp_serve == original.mcp_serve

    def test_gateway_loader_reads_config_yaml(self, tmp_path, monkeypatch):
        import gateway.config as gateway_config

        (tmp_path / "config.yaml").write_text(
            "mcp_serve:\n"
            "  enabled: true\n"
            "  transport: streamable_http\n"
            "  host: 127.0.0.1\n"
            "  port: 9010\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(gateway_config, "get_marlow_home", lambda: tmp_path)

        config = gateway_config.load_gateway_config()

        assert config.mcp_serve == MCPServeConfig(
            enabled=True,
            transport="streamable_http",
            host="127.0.0.1",
            port=9010,
        )


def test_http_mode_requires_bearer_token():
    pytest.importorskip("mcp")
    from mcp_serve import ManagedMCPHTTPServer

    with pytest.raises(ValueError, match="MARLOW_MCP_BEARER_TOKEN"):
        ManagedMCPHTTPServer(
            host="127.0.0.1",
            port=8765,
            bearer_token="",
        )


def test_http_start_reports_occupied_port():
    pytest.importorskip("mcp")
    from mcp_serve import ManagedMCPHTTPServer

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = int(occupied.getsockname()[1])
        service = ManagedMCPHTTPServer(
            host="127.0.0.1",
            port=port,
            bearer_token="test-token",
            startup_timeout=2,
        )

        with pytest.raises(RuntimeError, match="exited before startup"):
            service.start()


@pytest.mark.asyncio
async def test_authenticated_streamable_http_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    httpx = pytest.importorskip("httpx")
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.types import TextContent
    from mcp_serve import ManagedMCPHTTPServer

    monkeypatch.setenv("MARLOW_HOME", str(tmp_path))
    port = _unused_local_port()
    token = "test-token-with-sufficient-entropy"
    service = ManagedMCPHTTPServer(
        host="127.0.0.1",
        port=port,
        bearer_token=token,
    )

    await asyncio.to_thread(service.start)
    try:
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "marlow-test", "version": "1"},
            },
        }
        async with httpx.AsyncClient() as unauthenticated:
            response = await unauthenticated.post(
                service.endpoint,
                json=initialize,
                headers={"Accept": "application/json, text/event-stream"},
            )
            assert response.status_code == 401

        async with httpx.AsyncClient(
            headers={"Authorization": "Bearer wrong-token"}
        ) as invalid_client:
            response = await invalid_client.post(
                service.endpoint,
                json=initialize,
                headers={"Accept": "application/json, text/event-stream"},
            )
            assert response.status_code == 401

        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}
        ) as authenticated:
            async with streamable_http_client(
                service.endpoint,
                http_client=authenticated,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    result = await session.call_tool("conversations_list", {})

        assert {tool.name for tool in tools.tools} >= {
            "conversations_list",
            "messages_read",
            "messages_send",
        }
        assert result.isError is False
        assert isinstance(result.content[0], TextContent)
        payload = json.loads(result.content[0].text)
        assert payload["count"] == 0
    finally:
        await asyncio.to_thread(service.stop)


@pytest.mark.asyncio
async def test_gateway_manages_http_service_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setenv("MARLOW_HOME", str(tmp_path))
    monkeypatch.setenv("MARLOW_MCP_BEARER_TOKEN", "gateway-test-token")
    calls = []

    class FakeManagedServer:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def start(self):
            calls.append(("start", None))

        def stop(self):
            calls.append(("stop", None))

    monkeypatch.setattr("mcp_serve.ManagedMCPHTTPServer", FakeManagedServer)
    runner = GatewayRunner(
        GatewayConfig(
            mcp_serve=MCPServeConfig(
                enabled=True,
                host="127.0.0.1",
                port=9876,
            )
        )
    )

    await runner._start_managed_mcp_server()
    await runner._stop_managed_mcp_server()

    assert calls == [
        (
            "init",
            {
                "host": "127.0.0.1",
                "port": 9876,
                "bearer_token": "gateway-test-token",
                "auth_mode": "bearer",
                "public_url": None,
                "oauth_password": "",
            },
        ),
        ("start", None),
        ("stop", None),
    ]


@pytest.mark.asyncio
async def test_gateway_passes_oauth_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("MARLOW_HOME", str(tmp_path))
    monkeypatch.setenv("MARLOW_MCP_OAUTH_PASSWORD", "oauth-password-long-enough")
    calls = []

    class FakeManagedServer:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def start(self):
            calls.append(("start", None))

        def stop(self):
            calls.append(("stop", None))

    monkeypatch.setattr("mcp_serve.ManagedMCPHTTPServer", FakeManagedServer)
    runner = GatewayRunner(
        GatewayConfig(
            mcp_serve=MCPServeConfig(
                enabled=True,
                host="127.0.0.1",
                port=9877,
                auth="oauth",
                public_url="https://marlow.example",
            )
        )
    )

    await runner._start_managed_mcp_server()
    await runner._stop_managed_mcp_server()

    assert calls == [
        (
            "init",
            {
                "host": "127.0.0.1",
                "port": 9877,
                "bearer_token": "",
                "auth_mode": "oauth",
                "public_url": "https://marlow.example",
                "oauth_password": "oauth-password-long-enough",
            },
        ),
        ("start", None),
        ("stop", None),
    ]


@pytest.mark.asyncio
async def test_gateway_start_fails_when_managed_mcp_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("MARLOW_HOME", str(tmp_path))
    runner = GatewayRunner(GatewayConfig())
    monkeypatch.setattr(
        runner,
        "_start_managed_mcp_server",
        AsyncMock(side_effect=RuntimeError("port already in use")),
    )

    ok = await runner.start()

    assert ok is False
    assert runner._running is False
