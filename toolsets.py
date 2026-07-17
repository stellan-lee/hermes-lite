"""The single supported Hermes Lite toolset."""

from __future__ import annotations

from model_tools import DEFAULT_TOOL_NAMES

DEFAULT_TOOLSET = "hermes-lite"
TOOLSETS: dict[str, tuple[str, ...]] = {DEFAULT_TOOLSET: DEFAULT_TOOL_NAMES}


def get_toolset(name: str = DEFAULT_TOOLSET) -> tuple[str, ...]:
    """Return the named toolset or raise a clear error."""

    try:
        return TOOLSETS[name]
    except KeyError as exc:
        raise ValueError(f"unknown toolset: {name}") from exc
