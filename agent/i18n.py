"""English static-message catalog used by the CLI and gateway."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = (DEFAULT_LANGUAGE,)


def _flatten(node: Any, prefix: str, output: dict[str, str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            _flatten(value, f"{prefix}.{key}" if prefix else str(key), output)
    elif isinstance(node, str):
        output[prefix] = node


@lru_cache(maxsize=1)
def _catalog() -> dict[str, str]:
    import yaml

    path = Path(__file__).resolve().parent.parent / "locales" / "en.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    flattened: dict[str, str] = {}
    _flatten(raw, "", flattened)
    return flattened


def reset_language_cache() -> None:
    _catalog.cache_clear()


def get_language() -> str:
    return DEFAULT_LANGUAGE


def t(key: str, lang: str | None = None, **format_kwargs: Any) -> str:
    del lang
    value = _catalog().get(key, key)
    if not format_kwargs:
        return value
    try:
        return value.format(**format_kwargs)
    except (KeyError, IndexError, ValueError):
        return value


__all__ = ["DEFAULT_LANGUAGE", "SUPPORTED_LANGUAGES", "get_language", "reset_language_cache", "t"]
