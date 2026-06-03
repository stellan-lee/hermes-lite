"""Deterministic recall-query enrichment for external memory providers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecallQueryPlan:
    original_query: str
    recall_query: str
    intent: str | None
    entities: list[str]
    used_recent_context: bool
    # Deterministic, priority-ordered recall subqueries for multi-query
    # recall. Always recall-only — never persisted, never logged raw.
    # Empty when the original query is empty.
    subqueries: list[str] = field(default_factory=list)


_MEMORY_CONTEXT_RE = re.compile(
    r"<\s*memory-context\b[^>]*>[\s\S]*?</\s*memory-context\s*>",
    re.IGNORECASE,
)
_SYSTEM_NOTE_RE = re.compile(
    r"\[System note:\s*The following is recalled memory context,[^\]]*\]\s*",
    re.IGNORECASE,
)
_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
_XML_TOOLISH_RE = re.compile(
    r"<(?:tool|function|scratchpad|think)\b[\s\S]*?</(?:tool|function|scratchpad|think)>",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")

_CODEISH_RE = re.compile(
    r"\b(?:[a-zA-Z_][\w]*_[\w_]+|[a-z]+[A-Z][A-Za-z0-9]*|[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)+|[a-zA-Z_][\w]*(?:/[A-Za-z0-9_.-]+)+|[a-zA-Z_][\w]*(?:\.[A-Za-z_][\w]*)+)\b"
)
_QUOTED_RE = re.compile(r"['\"]([^'\"\n]{2,80})['\"]|[“”]([^“”\n]{2,80})[“”]|[‘’]([^‘’\n]{2,80})[‘’]")
_CAP_PHRASE_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){1,5}\b")
_TOPIC_NEAR_RE = re.compile(
    r"(?:about|for|regarding|re:|on|关于)\s+([^,.;:!?，。！？\n]{2,80})",
    re.IGNORECASE,
)

_INTENT_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "previous decision / final agreed approach",
        ("what did we decide", "decision", "agreed", "settled", "final", "previously decided"),
        ("决定", "定了", "之前怎么说", "上次", "最终", "方案", "怎么定"),
    ),
    (
        "implementation detail / constraints",
        (
            "how implement",
            "how should we implement",
            "implementation",
            "code",
            "bug",
            "fix",
            "error",
            "path",
        ),
        ("怎么实现", "代码", "bug", "报错", "修", "路径"),
    ),
    (
        "user preference",
        ("prefer", "preference", "format", "style", "how do i like"),
        ("偏好", "喜欢", "格式", "风格"),
    ),
    (
        "task status / open todo",
        ("todo", "next", "status", "where were we", "open question"),
        ("下一步", "待办", "进度", "还剩", "卡在哪"),
    ),
    # Placed last so it only catches queries no stronger intent matched
    # (e.g. "we must decide" stays a decision). Addresses the PR4 eval gap
    # where constraint recall queries got no intent at all.
    (
        "constraint / requirement",
        ("constraint", "requirement", "must not", "must", "cannot", "can't",
         "logging constraint", "restriction", "not allowed"),
        ("限制", "要求", "必须", "不能", "不要", "只能"),
    ),
)

# Maps each ``_INTENT_RULES`` label to a focused, recall-friendly suffix used
# to build the intent-specific subquery ("<topic> <suffix>"). Keys MUST stay
# in sync with the labels above — ``test_every_intent_label_has_subquery_suffix``
# fails loudly if a label is added/renamed without updating this table.
# Each suffix keeps its original recall phrasing first (existing callers/tests
# depend on those exact substrings), then appends structured-card-friendly
# terms ("type: <card-type>" plus label phrases) so subqueries also match the
# structured memory cards written by PR4 — without special-casing recall.
# The appended terms are best-effort: under a tight ``max_subquery_chars`` the
# subquery is bounded by ``_limit_text`` and the trailing ``type:`` terms may
# be truncated, degrading gracefully to the original recall phrasing.
_INTENT_SUBQUERY_SUFFIX: dict[str, str] = {
    "previous decision / final agreed approach": (
        "previous decision final agreed approach type: decision final decision "
        "status: active current decision not superseded latest active decision"
    ),
    "implementation detail / constraints": (
        "implementation details constraints code path type: implementation_detail"
    ),
    "user preference": (
        "user preference style format type: preference preferred format"
    ),
    "task status / open todo": (
        "task status todo open question next step type: todo"
    ),
    "constraint / requirement": (
        "constraint requirement restriction type: constraint status: active"
    ),
}


def build_recall_query_plan(
    original_user_message: object,
    recent_messages: list[dict] | None = None,
    *,
    max_recent_turns: int = 6,
    max_recent_chars: int = 1200,
    max_query_chars: int = 1800,
    max_queries: int = 4,
    max_subquery_chars: int | None = None,
) -> RecallQueryPlan:
    """Build one local, deterministic recall query from current user input.

    Also derives a small, priority-ordered list of recall ``subqueries`` for
    multi-query recall. ``max_subquery_chars`` defaults to ``max_query_chars``.
    """
    original_query = _clean_text(
        original_user_message if isinstance(original_user_message, str) else ""
    )
    max_recent_turns = max(0, int(max_recent_turns or 0))
    max_recent_chars = max(0, int(max_recent_chars or 0))
    max_query_chars = max(1, int(max_query_chars or 1))
    max_queries = max(1, int(max_queries or 1))
    if max_subquery_chars is None:
        max_subquery_chars = max_query_chars
    max_subquery_chars = max(1, int(max_subquery_chars or 1))

    if not original_query:
        return RecallQueryPlan("", "", None, [], False, [])

    intent = _detect_intent(original_query)
    recent_lines = _recent_context_lines(
        recent_messages,
        original_query=original_query,
        max_recent_turns=max_recent_turns,
        max_recent_chars=max_recent_chars,
    )
    recent_text = "\n".join(recent_lines)
    entities = _extract_entities(original_query + "\n" + recent_text)

    if not intent and not recent_lines and not entities:
        recall_query = _limit_text(original_query, max_query_chars)
        return RecallQueryPlan(
            original_query,
            recall_query,
            None,
            [],
            False,
            _build_subqueries(
                original_query, recall_query, None, [], max_queries, max_subquery_chars
            ),
        )

    parts = ["Original question:", original_query]
    if recent_lines:
        parts.extend(["", "Recent conversation context:", recent_text])
    if intent:
        parts.extend(["", "Recall intent:", intent])
    if entities:
        parts.extend(["", "Key terms:", "; ".join(entities[:12])])

    recall_query = _limit_text("\n".join(parts).strip(), max_query_chars)
    if original_query not in recall_query:
        recall_query = _limit_text(original_query, max_query_chars)

    return RecallQueryPlan(
        original_query=original_query,
        recall_query=recall_query,
        intent=intent,
        entities=entities,
        used_recent_context=bool(recent_lines),
        subqueries=_build_subqueries(
            original_query, recall_query, intent, entities, max_queries, max_subquery_chars
        ),
    )


def _build_subqueries(
    original_query: str,
    recall_query: str,
    intent: str | None,
    entities: list[str],
    max_queries: int,
    max_subquery_chars: int,
) -> list[str]:
    """Derive priority-ordered recall subqueries (deterministic, recall-only).

    Order: original query, PR2 enriched query, intent-specific query,
    entity-heavy query. Each is bounded, normalized-duplicate subqueries are
    dropped (priority order preserved), and the list is capped at
    ``max_queries``. All inputs are already sanitized by the builder, so no
    system/developer/tool/memory-context content can leak in here.
    """
    candidates: list[str] = []

    # 1. Original (cleaned) user query — always, when non-empty.
    if original_query:
        candidates.append(original_query)

    # 2. PR2 enriched recall query — only when it differs from the original.
    if recall_query and recall_query != original_query:
        candidates.append(recall_query)

    topic = _subquery_topic(entities, original_query)

    # 3. Intent-specific query — only when an intent is detected and it adds a
    #    focused suffix on top of a topic.
    if intent and topic:
        suffix = _INTENT_SUBQUERY_SUFFIX.get(intent)
        if suffix:
            candidates.append(f"{topic} {suffix}")

    # 4. Entity-heavy query — only when there are enough entities to make a
    #    distinct, focused lookup worthwhile.
    if len(entities) >= 2:
        candidates.append(" ".join(entities[:8]))

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        bounded = _limit_text(candidate.strip(), max_subquery_chars) if candidate else ""
        if not bounded:
            continue
        key = _normalize_for_dedupe(bounded)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(bounded)
        if len(out) >= max_queries:
            break
    return out


def _subquery_topic(entities: list[str], original_query: str) -> str:
    """Pick a short topic string for intent subqueries (entities, else query)."""
    if entities:
        return " ".join(entities[:6])
    return original_query


def _normalize_for_dedupe(text: str) -> str:
    """Whitespace-collapsed, casefolded key for subquery duplicate detection."""
    return _WHITESPACE_RE.sub(" ", text).strip().casefold()


def _clean_text(value: Any) -> str:
    text = _content_to_text(value)
    if not text:
        return ""
    text = _MEMORY_CONTEXT_RE.sub(" ", text)
    text = _SYSTEM_NOTE_RE.sub(" ", text)
    text = _FENCED_CODE_RE.sub(" ", text)
    text = _XML_TOOLISH_RE.sub(" ", text)
    text = "\n".join(_clean_line(line) for line in text.splitlines())
    return _WHITESPACE_RE.sub(" ", text).strip()


def _content_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if (
                isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def _clean_line(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    if len(line) > 240:
        line = line[:240]
    if (
        line.count("{") + line.count("}") + line.count("[") + line.count("]")
        > 24
    ):
        return ""
    return line


def _recent_context_lines(
    recent_messages: list[dict] | None,
    *,
    original_query: str,
    max_recent_turns: int,
    max_recent_chars: int,
) -> list[str]:
    if not recent_messages or max_recent_turns <= 0 or max_recent_chars <= 0:
        return []

    candidates: list[tuple[str, str]] = []
    for msg in reversed(recent_messages):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in {"user", "assistant"}:
            continue
        if role == "assistant" and msg.get("tool_calls"):
            continue
        text = _clean_text(msg.get("content", ""))
        if not text or text == original_query:
            continue
        candidates.append((role, text))
        if len(candidates) >= max_recent_turns * 2:
            break

    selected = list(reversed(candidates))
    lines: list[str] = []
    total = 0
    for role, text in selected:
        line = f"{role}: {text}"
        remaining = max_recent_chars - total
        if remaining <= 0:
            break
        if len(line) > remaining:
            line = line[:remaining].rstrip()
        if line:
            lines.append(line)
            total += len(line) + 1
    return lines


def _detect_intent(query: str) -> str | None:
    lowered = query.casefold()
    compact = lowered.replace(" ", "")
    for label, english_needles, chinese_needles in _INTENT_RULES:
        if any(needle in lowered for needle in english_needles):
            return label
        if any(needle in query or needle in compact for needle in chinese_needles):
            return label
    return None


def _extract_entities(text: str) -> list[str]:
    seen: set[str] = set()
    entities: list[str] = []

    def add(value: str) -> None:
        value = _WHITESPACE_RE.sub(" ", value.strip(" \t\r\n.,;:!?，。！？()[]{}<>"))
        if len(value) < 2 or len(value) > 90:
            return
        key = value.casefold()
        if key in seen:
            return
        seen.add(key)
        entities.append(value)

    for regex in (_QUOTED_RE, _CODEISH_RE, _CAP_PHRASE_RE, _TOPIC_NEAR_RE):
        for match in regex.finditer(text):
            groups = (
                [g for g in match.groups() if g]
                if match.groups()
                else [match.group(0)]
            )
            for group in groups:
                if regex is _TOPIC_NEAR_RE:
                    for sep in (" and ", " 和 "):
                        if sep in group:
                            group = group.split(sep, 1)[0]
                            break
                add(group)
    return entities


def _limit_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()
