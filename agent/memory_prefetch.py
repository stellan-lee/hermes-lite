"""Small helpers for keyed external-memory prefetch caches."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any


def _coerce_prefetch_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def normalize_prefetch_query(query: Any) -> str:
    """Normalize whitespace for query identity without storing raw text."""
    return " ".join(_coerce_prefetch_value(query).split()).casefold()


def short_hash(value: Any) -> str:
    text = _coerce_prefetch_value(value)
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:12]


def make_prefetch_key(query: str, *, session_id: str = "", effective_scope: str = "") -> dict[str, str]:
    """Build a stable, non-content cache key for a prefetch result."""
    query_hash = short_hash(normalize_prefetch_query(query))
    session_hash = short_hash(session_id or "")
    scope_hash = short_hash(effective_scope or "")
    payload = json.dumps(
        {"q": query_hash, "sid": session_hash, "scope": scope_hash},
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "key": short_hash(payload),
        "query_hash": query_hash,
        "session_hash": session_hash,
        "scope_hash": scope_hash,
    }


def make_prefetch_entry(
    result: str,
    query: str,
    *,
    session_id: str = "",
    effective_scope: str = "",
    fired_at: int | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        **make_prefetch_key(query, session_id=session_id, effective_scope=effective_scope),
        "created_at": time.time(),
        "result": result or "",
    }
    if fired_at is not None:
        entry["fired_at"] = fired_at
    return entry


def prefetch_entry_matches(
    entry: Any,
    query: str,
    *,
    session_id: str = "",
    effective_scope: str = "",
) -> bool:
    if not isinstance(entry, dict):
        return False
    expected = make_prefetch_key(
        query,
        session_id=session_id,
        effective_scope=effective_scope,
    )
    return (
        entry.get("key") == expected["key"]
        and entry.get("query_hash") == expected["query_hash"]
        and entry.get("session_hash") == expected["session_hash"]
        and entry.get("scope_hash") == expected["scope_hash"]
    )


def prefetch_entry_result(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    result = entry.get("result", "")
    return result if isinstance(result, str) else ""
