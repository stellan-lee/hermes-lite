"""Provider-neutral web search and extraction tools."""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any

from tools.registry import registry, tool_error


def _discover_providers() -> None:
    from marlow_cli.plugins import _ensure_plugins_discovered

    _ensure_plugins_discovered()


def _active_search_provider():
    from agent.web_search_registry import get_active_search_provider

    _discover_providers()
    return get_active_search_provider()


def _active_extract_provider():
    from agent.web_search_registry import get_active_extract_provider

    _discover_providers()
    return get_active_extract_provider()


def check_web_api_key() -> bool:
    """Return whether a registered web provider is currently available."""
    try:
        from agent.web_search_registry import list_providers

        _discover_providers()
        return any(provider.is_available() for provider in list_providers())
    except Exception:
        return False


def web_search_tool(query: str, limit: int = 5) -> str:
    if not isinstance(query, str) or not query.strip():
        return tool_error("query is required for web search")
    provider = _active_search_provider()
    if provider is None:
        return json.dumps(
            {
                "success": False,
                "error": "No available web search provider. Configure Brave Search or DuckDuckGo.",
            }
        )
    result = provider.search(query.strip(), max(1, min(int(limit), 100)))
    return json.dumps(result)


async def web_extract_tool(urls: list[str], format: str = "markdown") -> str:
    del format
    if not urls:
        return tool_error("urls is required for web extraction")
    # Match browser navigation's exfiltration guard before provider
    # resolution so a missing extract plugin cannot mask a blocked secret.
    import urllib.parse
    from agent.redact import _PREFIX_RE

    for url in urls[:5]:
        decoded = urllib.parse.unquote(str(url))
        if _PREFIX_RE.search(str(url)) or _PREFIX_RE.search(decoded):
            return json.dumps(
                {
                    "success": False,
                    "error": "Blocked: URL contains what appears to be an API key or token. Secrets must not be sent in URLs.",
                }
            )
    provider = _active_extract_provider()
    if provider is None:
        return json.dumps(
            {
                "success": False,
                "error": "No installed web provider supports page extraction.",
            }
        )
    result = provider.extract(urls[:5])
    if inspect.isawaitable(result):
        result = await result
    else:
        result = await asyncio.to_thread(lambda: result)
    return json.dumps({"success": True, "data": result})


WEB_SEARCH_SCHEMA = {
    "name": "web_search",
    "description": "Search the web using the configured provider.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 5},
        },
        "required": ["query"],
    },
}

WEB_EXTRACT_SCHEMA = {
    "name": "web_extract",
    "description": "Extract page content using a configured provider that supports extraction.",
    "parameters": {
        "type": "object",
        "properties": {
            "urls": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        },
        "required": ["urls"],
    },
}

registry.register(
    name="web_search",
    toolset="web",
    schema=WEB_SEARCH_SCHEMA,
    handler=lambda args, **_kw: web_search_tool(args.get("query", ""), args.get("limit", 5)),
    check_fn=check_web_api_key,
    requires_env=["BRAVE_SEARCH_API_KEY"],
    emoji="🔍",
    max_result_size_chars=100_000,
)
registry.register(
    name="web_extract",
    toolset="web",
    schema=WEB_EXTRACT_SCHEMA,
    handler=lambda args, **_kw: web_extract_tool(
        args.get("urls", [])[:5] if isinstance(args.get("urls"), list) else []
    ),
    check_fn=check_web_api_key,
    requires_env=["BRAVE_SEARCH_API_KEY"],
    is_async=True,
    emoji="📄",
    max_result_size_chars=100_000,
)
