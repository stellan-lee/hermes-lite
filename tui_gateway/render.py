"""TUI rendering compatibility hooks.

The retained Ink frontend owns markdown and diff rendering, so the Python
gateway returns ``None`` and lets the client render each payload.
"""

from __future__ import annotations


def render_message(text: str, cols: int = 80) -> str | None:
    del text, cols
    return None


def render_diff(text: str, cols: int = 80) -> str | None:
    del text, cols
    return None


def make_stream_renderer(cols: int = 80):
    del cols
    return None
