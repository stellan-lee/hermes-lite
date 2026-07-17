"""Fixed transport registry for the retained Codex Responses adapter."""

import importlib

from agent.transports.types import (
    NormalizedResponse,
    ToolCall,
    Usage,
    build_tool_call,
    map_finish_reason,
)

__all__ = [
    "NormalizedResponse",
    "ToolCall",
    "Usage",
    "build_tool_call",
    "get_transport",
    "map_finish_reason",
    "register_transport",
]

_REGISTRY: dict = {}
_discovered: bool = False


def register_transport(api_mode: str, transport_cls: type) -> None:
    """Register a transport class for an api_mode string."""
    _REGISTRY[api_mode] = transport_cls


def get_transport(api_mode: str):
    """Return a Codex transport instance, or ``None`` for unsupported modes."""
    global _discovered
    if not _discovered:
        _discover_transports()
    cls = _REGISTRY.get(api_mode)
    if cls is None:
        return None
    return cls()


def _discover_transports() -> None:
    """Import the one retained transport to trigger auto-registration."""
    global _discovered
    _discovered = True
    importlib.import_module("agent.transports.codex")
