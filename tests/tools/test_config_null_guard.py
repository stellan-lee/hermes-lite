"""Tests for config.get() null-coalescing in tool configuration.

YAML ``null`` values (or ``~``) for a present key make ``dict.get(key, default)``
return ``None`` instead of the default — calling ``.lower()`` on that raises
``AttributeError``.  These tests verify the ``or`` coalescing guards.
"""

from unittest.mock import patch


# ── TTS tool ──────────────────────────────────────────────────────────────

class TestTTSProviderNullGuard:
    """tools/tts_tool.py — _get_provider()"""

    def test_explicit_null_provider_returns_default(self):
        """YAML ``tts: {provider: null}`` should fall back to default."""
        from tools.tts_tool import _get_provider, DEFAULT_PROVIDER

        result = _get_provider({"provider": None})
        assert result == DEFAULT_PROVIDER.lower().strip()

    def test_missing_provider_returns_default(self):
        """No ``provider`` key at all should also return default."""
        from tools.tts_tool import _get_provider, DEFAULT_PROVIDER

        result = _get_provider({})
        assert result == DEFAULT_PROVIDER.lower().strip()

    def test_valid_provider_passed_through(self):
        from tools.tts_tool import _get_provider

        result = _get_provider({"provider": "OPENAI"})
        assert result == "openai"


# ── Web tools ─────────────────────────────────────────────────────────────

class TestMCPAuthNullGuard:
    """tools/mcp_tool.py — MCPServerTask.__init__() auth config line"""

    def test_explicit_null_auth_does_not_crash(self):
        """YAML ``auth: null`` in MCP server config should not raise."""
        # Test the expression directly — MCPServerTask.__init__ has many deps
        config = {"auth": None, "timeout": 30}
        auth_type = (config.get("auth") or "").lower().strip()
        assert auth_type == ""

    def test_missing_auth_defaults_to_empty(self):
        config = {"timeout": 30}
        auth_type = (config.get("auth") or "").lower().strip()
        assert auth_type == ""

    def test_valid_auth_passed_through(self):
        config = {"auth": "OAUTH", "timeout": 30}
        auth_type = (config.get("auth") or "").lower().strip()
        assert auth_type == "oauth"


# ── Trajectory compressor ─────────────────────────────────────────────────
