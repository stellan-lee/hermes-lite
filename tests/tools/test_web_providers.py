"""Tests for the web tools provider architecture.

Covers:
- WebSearchProvider / WebExtractProvider ABC enforcement
- Per-capability backend selection (_get_search_backend, _get_extract_backend)
- Backward compatibility (web.backend still works as shared fallback)
- Config keys merge correctly via DEFAULT_CONFIG
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from tests.tools.conftest import register_all_web_providers


# ---------------------------------------------------------------------------
# ABC enforcement
# ---------------------------------------------------------------------------


class TestWebProviderABCs:
    """The unified WebSearchProvider ABC enforces the interface contract.

    After PR #25182, all seven providers are subclasses of
    :class:`agent.web_search_provider.WebSearchProvider`. The legacy
    in-tree ABCs at ``tools.web_providers.base`` (separate
    ``WebSearchProvider`` + ``WebExtractProvider``) were deleted in the
    same PR — providers now advertise capabilities via
    ``supports_search() / supports_extract()`` flags.
    """

    def test_cannot_instantiate_abc_directly(self):
        from agent.web_search_provider import WebSearchProvider

        with pytest.raises(TypeError):
            WebSearchProvider()  # type: ignore[abstract]

    def test_concrete_search_only_provider_works(self):
        from agent.web_search_provider import WebSearchProvider

        class Dummy(WebSearchProvider):
            @property
            def name(self) -> str:
                return "dummy"

            @property
            def display_name(self) -> str:
                return "Dummy Search"

            def is_available(self) -> bool:
                return True

            def supports_search(self) -> bool:
                return True

            def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
                return {"success": True, "data": {"web": []}}

        d = Dummy()
        assert d.name == "dummy"
        assert d.display_name == "Dummy Search"
        assert d.is_available() is True
        assert d.supports_search() is True
        assert d.supports_extract() is False  # default
        assert d.search("test")["success"] is True

    def test_concrete_multi_capability_provider_works(self):
        from agent.web_search_provider import WebSearchProvider

        class Dummy(WebSearchProvider):
            @property
            def name(self) -> str:
                return "dummy"

            @property
            def display_name(self) -> str:
                return "Dummy Multi"

            def is_available(self) -> bool:
                return True

            def supports_search(self) -> bool:
                return True

            def supports_extract(self) -> bool:
                return True

            def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
                return {"success": True, "data": {"web": []}}

            def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
                return [{"url": urls[0], "content": "x"}]

        d = Dummy()
        assert d.supports_search() is True
        assert d.supports_extract() is True
        assert d.extract(["https://example.com"])[0]["url"] == "https://example.com"

    def test_search_only_provider_skips_extract(self):
        """Search-only providers don't have to implement extract()."""
        from agent.web_search_provider import WebSearchProvider

        class SearchOnly(WebSearchProvider):
            @property
            def name(self) -> str:
                return "search-only"

            @property
            def display_name(self) -> str:
                return "Search Only"

            def is_available(self) -> bool:
                return True

            def supports_search(self) -> bool:
                return True

            def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
                return {"success": True, "data": {"web": []}}

        # Should instantiate fine — extract has default supports_*()
        # returning False and isn't required to be overridden when not
        # advertised.
        s = SearchOnly()
        assert s.supports_search() is True
        assert s.supports_extract() is False


# ---------------------------------------------------------------------------
# Per-capability backend selection
# ---------------------------------------------------------------------------


class TestDefaultConfig:
    """The web section exists in DEFAULT_CONFIG with per-capability keys."""

    def test_web_section_in_default_config(self):
        from marlow_cli.config import DEFAULT_CONFIG

        assert "web" in DEFAULT_CONFIG
        web = DEFAULT_CONFIG["web"]
        assert "backend" in web
        assert "search_backend" in web
        assert "extract_backend" in web
        # All empty string by default (no override)
        assert web["backend"] == ""
        assert web["search_backend"] == ""
        assert web["extract_backend"] == ""


# ---------------------------------------------------------------------------
# web_search_tool uses _get_search_backend
# ---------------------------------------------------------------------------

