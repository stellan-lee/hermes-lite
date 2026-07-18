"""Tests for the shared httpx.Limits helper that all long-lived platform
adapters use to tighten their keep-alive pool.

Context: #18451 — on macOS behind Cloudflare Warp, httpx's default
keepalive_expiry=5s let idle CLOSE_WAIT sockets accumulate across
multiple long-lived gateway adapters (QQ Bot, Feishu, WeCom, DingTalk,
Signal, BlueBubbles, WeCom-callback) until the process hit the default
256 fd limit.  These tests just verify the helper returns sensibly
tuned limits and respects env-var overrides; the actual fd-pressure
behaviour is only observable at runtime under load.
"""

from __future__ import annotations
import pytest


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("HERMES_GATEWAY_HTTPX_KEEPALIVE_EXPIRY", raising=False)
    monkeypatch.delenv("HERMES_GATEWAY_HTTPX_MAX_KEEPALIVE", raising=False)


def test_returns_none_when_httpx_unavailable(monkeypatch):
    """If httpx can't be imported, the helper returns None so callers
    fall back to httpx's built-in Limits default without raising."""
    import gateway.platforms._http_client_limits as mod

    monkeypatch.setattr(mod, "httpx", None)
    assert mod.platform_httpx_limits() is None


def test_default_limits_tighten_keepalive_below_httpx_default():
    import httpx
    from gateway.platforms._http_client_limits import platform_httpx_limits

    limits = platform_httpx_limits()
    assert isinstance(limits, httpx.Limits)
    assert limits.keepalive_expiry is not None
    assert limits.keepalive_expiry < 5.0
    assert limits.max_keepalive_connections is not None
    assert 1 <= limits.max_keepalive_connections <= 50


def test_env_override_keepalive_expiry(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_HTTPX_KEEPALIVE_EXPIRY", "7.5")
    from gateway.platforms._http_client_limits import platform_httpx_limits

    limits = platform_httpx_limits()
    assert limits.keepalive_expiry == 7.5


def test_env_override_max_keepalive(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_HTTPX_MAX_KEEPALIVE", "25")
    from gateway.platforms._http_client_limits import platform_httpx_limits

    limits = platform_httpx_limits()
    assert limits.max_keepalive_connections == 25


def test_env_override_rejects_garbage(monkeypatch):
    """Malformed env values fall back to defaults rather than raising."""
    monkeypatch.setenv("HERMES_GATEWAY_HTTPX_KEEPALIVE_EXPIRY", "not-a-number")
    monkeypatch.setenv("HERMES_GATEWAY_HTTPX_MAX_KEEPALIVE", "-3")
    from gateway.platforms._http_client_limits import platform_httpx_limits

    limits = platform_httpx_limits()
    assert limits.keepalive_expiry is not None and limits.keepalive_expiry > 0
    assert limits.max_keepalive_connections is not None
    assert limits.max_keepalive_connections > 0
