"""Deterministic recall-query enrichment for external memory providers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class RecallQueryPlan:
    original_query: str
    recall_query: str
    intent: str | None
    entities: list[str]
    used_recent_context: bool


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
)


def build_recall_query_plan(
    original_user_message: object,
    recent_messages: list[dict] | None = None,
    *,
    max_recent_turns: int = 6,
    max_recent_chars: int = 1200,
    max_query_chars: int = 1800,
) -> RecallQueryPlan:
    """Build one local, deterministic recall query from current user input."""
    original_query = _clean_text(
        original_user_message if isinstance(original_user_message, str) else ""
    )
    max_recent_turns = max(0, int(max_recent_turns or 0))
    max_recent_chars = max(0, int(max_recent_chars or 0))
    max_query_chars = max(1, int(max_query_chars or 1))

    if not original_query:
        return RecallQueryPlan("", "", None, [], False)

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
        return RecallQueryPlan(
            original_query,
            _limit_text(original_query, max_query_chars),
            None,
            [],
            False,
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
    )


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
