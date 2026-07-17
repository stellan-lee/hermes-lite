"""The complete built-in tool set for Hermes Lite."""

# Explicit imports replace the old filesystem discovery and plugin hooks.
from tools import file_tools as _file_tools  # noqa: F401
from tools import terminal_tool as _terminal_tool  # noqa: F401
from tools.registry import ToolContext, ToolDefinition, ToolRegistry, registry

__all__ = ["ToolContext", "ToolDefinition", "ToolRegistry", "registry"]
