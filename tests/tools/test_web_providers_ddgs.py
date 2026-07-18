"""Tests for the DuckDuckGo (ddgs) web search provider.

Covers:
- DDGSWebSearchProvider.is_available() — reflects package importability
- DDGSWebSearchProvider.search() — happy path, missing package, runtime error
- Result normalization (title, url, description, position)
- _is_backend_available("ddgs") / _get_backend() integration
- web_extract returns a search-only error when ddgs is active
"""
from __future__ import annotations

import json
import sys
import types

import pytest

from tests.tools.conftest import register_all_web_providers


def _install_fake_ddgs(monkeypatch, *, text_results=None, text_raises=None):
    """Install a stub ``ddgs`` module in sys.modules for the duration of a test.

    ``text_results``: iterable of dicts to yield from DDGS().text(...).
    ``text_raises``: if set, DDGS().text raises this exception instead.
    """
    fake = types.ModuleType("ddgs")

    class _FakeDDGS:
        def __enter__(self):
            return self
        def __exit__(self, *_a):
            return False
        def text(self, query, max_results=5):
            if text_raises is not None:
                raise text_raises
            for hit in (text_results or []):
                yield hit

    fake.DDGS = _FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake)
    return fake


# ---------------------------------------------------------------------------
# DDGSWebSearchProvider unit tests
# ---------------------------------------------------------------------------


class TestDDGSProviderIsConfigured:
    def test_configured_when_package_importable(self, monkeypatch):
        _install_fake_ddgs(monkeypatch)
        # Drop any cached ``plugins.web.ddgs.provider`` so is_configured re-imports ddgs fresh
        monkeypatch.delitem(sys.modules, "plugins.web.ddgs.provider", raising=False)
        from plugins.web.ddgs.provider import DDGSWebSearchProvider
        assert DDGSWebSearchProvider().is_available() is True

    def test_not_configured_when_package_missing(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "ddgs", raising=False)
        monkeypatch.delitem(sys.modules, "plugins.web.ddgs.provider", raising=False)
        # Block the import so ``import ddgs`` raises ImportError even if the package is actually installed
        import builtins
        orig_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "ddgs":
                raise ImportError("blocked for test")
            return orig_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked_import)
        from plugins.web.ddgs.provider import DDGSWebSearchProvider
        assert DDGSWebSearchProvider().is_available() is False

    def test_provider_name(self):
        from plugins.web.ddgs.provider import DDGSWebSearchProvider
        assert DDGSWebSearchProvider().name == "ddgs"

    def test_implements_web_search_provider(self):
        from agent.web_search_provider import WebSearchProvider
        from plugins.web.ddgs.provider import DDGSWebSearchProvider
        assert issubclass(DDGSWebSearchProvider, WebSearchProvider)


class TestDDGSProviderSearch:
    def test_happy_path_normalizes_results(self, monkeypatch):
        _install_fake_ddgs(monkeypatch, text_results=[
            {"title": "A", "href": "https://a.example.com", "body": "desc A"},
            {"title": "B", "href": "https://b.example.com", "body": "desc B"},
            {"title": "C", "href": "https://c.example.com", "body": "desc C"},
        ])
        from plugins.web.ddgs.provider import DDGSWebSearchProvider

        result = DDGSWebSearchProvider().search("q", limit=5)

        assert result["success"] is True
        web = result["data"]["web"]
        assert len(web) == 3
        assert web[0] == {"title": "A", "url": "https://a.example.com", "description": "desc A", "position": 1}
        assert web[2]["position"] == 3

    def test_accepts_url_key_as_fallback_for_href(self, monkeypatch):
        _install_fake_ddgs(monkeypatch, text_results=[
            {"title": "A", "url": "https://a.example.com", "body": "desc A"},
        ])
        from plugins.web.ddgs.provider import DDGSWebSearchProvider

        result = DDGSWebSearchProvider().search("q", limit=5)

        assert result["success"] is True
        assert result["data"]["web"][0]["url"] == "https://a.example.com"

    def test_limit_is_respected(self, monkeypatch):
        _install_fake_ddgs(monkeypatch, text_results=[
            {"title": f"R{i}", "href": f"https://r{i}.example.com", "body": ""}
            for i in range(10)
        ])
        from plugins.web.ddgs.provider import DDGSWebSearchProvider

        result = DDGSWebSearchProvider().search("q", limit=3)

        assert result["success"] is True
        assert len(result["data"]["web"]) == 3

    def test_missing_package_returns_failure(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "ddgs", raising=False)
        monkeypatch.delitem(sys.modules, "plugins.web.ddgs.provider", raising=False)
        import builtins
        orig_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "ddgs":
                raise ImportError("blocked for test")
            return orig_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked_import)
        from plugins.web.ddgs.provider import DDGSWebSearchProvider

        result = DDGSWebSearchProvider().search("q", limit=5)
        assert result["success"] is False
        assert "ddgs" in result["error"].lower()

    def test_runtime_error_returns_failure(self, monkeypatch):
        _install_fake_ddgs(monkeypatch, text_raises=RuntimeError("rate limited 202"))
        from plugins.web.ddgs.provider import DDGSWebSearchProvider

        result = DDGSWebSearchProvider().search("q", limit=5)
        assert result["success"] is False
        assert "rate limited" in result["error"] or "failed" in result["error"].lower()

    def test_empty_results(self, monkeypatch):
        _install_fake_ddgs(monkeypatch, text_results=[])
        from plugins.web.ddgs.provider import DDGSWebSearchProvider

        result = DDGSWebSearchProvider().search("nothing", limit=5)
        assert result["success"] is True
        assert result["data"]["web"] == []


# ---------------------------------------------------------------------------
# Integration: _is_backend_available / _get_backend / check_web_api_key
# ---------------------------------------------------------------------------
