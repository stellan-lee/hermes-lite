"""Model-name normalization for retained Hermes runtimes."""

from __future__ import annotations


_AGGREGATOR_PROVIDERS: frozenset[str] = frozenset()


def normalize_model_for_provider(model_input: str, target_provider: str) -> str:
    """Normalize Codex prefixes; preserve custom/local model identifiers."""
    model = str(model_input or "").strip()
    provider = str(target_provider or "").strip().lower()
    if not model:
        return ""
    if provider in {"openai-codex", "codex"} and "/" in model:
        prefix, bare = model.split("/", 1)
        if prefix.lower() in {"openai", "openai-codex", "codex"} and bare.strip():
            return bare.strip()
    return model
