"""Shared helpers for tool backend selection."""

from __future__ import annotations

import os
from typing import Any


_DEFAULT_BROWSER_PROVIDER = "local"




def resolve_openai_audio_api_key() -> str:
    """Prefer the voice-tools key, but fall back to the normal OpenAI key."""
    return (
        os.getenv("VOICE_TOOLS_OPENAI_KEY", "")
        or os.getenv("OPENAI_API_KEY", "")
    ).strip()
