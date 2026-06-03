"""Deterministic structured memory cards (PR4).

After a completed turn, Hermes can distil a few small, structured "memory
cards" — durable signals like decisions, preferences, todos, constraints,
implementation details, and open questions — and write them into external
memory so future *recall* finds them more reliably.

Design constraints (kept deliberately small and reviewable):

- No LLM calls. Extraction is pure deterministic keyword/heuristic logic.
- No external dependencies.
- Cards are recall-only provenance: they are written to memory providers
  *after* the turn and only ever re-enter a model call if normal memory
  recall retrieves them later. They never touch the current turn's recall,
  the current API call, or persistent conversation history.
- Cards never contain raw system/developer/tool content, ``<memory-context>``
  blocks, fenced code, or huge tool blobs — those are stripped before any
  text is considered, and summaries are bounded.

This module is a sibling of :mod:`agent.memory_recall_query` (PR2) and
reuses its sanitizing regexes and entity extraction so the two stay
consistent. Cross-turn "superseded memory" updates are intentionally out
of scope for PR4 (a possible PR5).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from agent.memory_recall_query import (
    _FENCED_CODE_RE,
    _MEMORY_CONTEXT_RE,
    _SYSTEM_NOTE_RE,
    _XML_TOOLISH_RE,
    _content_to_text,
    _extract_entities,
)


class MemoryCardType:
    """Stable string values for the kinds of durable signal we capture."""

    DECISION = "decision"
    PREFERENCE = "preference"
    TODO = "todo"
    CONSTRAINT = "constraint"
    IMPLEMENTATION_DETAIL = "implementation_detail"
    OPEN_QUESTION = "open_question"


class MemoryCardStatus:
    """Lifecycle status of a card.

    PR4 emits active/open. PR5 adds ``superseded`` (append-only): a new card
    can mark a prior card superseded via metadata + a marker card — old
    provider memories are never deleted or rewritten.
    """

    ACTIVE = "active"
    OPEN = "open"
    REJECTED = "rejected"  # reserved
    SUPERSEDED = "superseded"  # PR5 — set on marker cards only


@dataclass
class MemoryCard:
    """One structured, durable memory signal extracted from a turn.

    ``card_id`` is deterministic from the card's CONTENT + session hash
    (type/title/summary/entities/session) so re-extracting the same turn
    yields stable identifiers (useful for dedupe and idempotent provider
    writes). It deliberately does NOT include the PR5 supersession fields
    (``supersedes``/``superseded_by``/``conflict_group_id``): those are
    derived post-hoc from a volatile candidate search and must not perturb
    the stable content id. ``source_turn_hash`` is a hash of the (sanitized)
    turn text — provenance without exposing raw content.

    PR5 supersession fields are optional and default empty, so all PR4 cards
    remain backward compatible.
    """

    card_id: str
    type: str
    status: str
    title: str
    summary: str
    entities: list[str] = field(default_factory=list)
    confidence: str = "medium"
    source_session_id: str = ""
    source_turn_hash: str = ""
    # PR5 — append-only supersession metadata.
    supersedes: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    conflict_group_id: str | None = None


# ---------------------------------------------------------------------------
# Signal tables — deterministic heuristics only.
#
# Order matters: a sentence is classified as the FIRST matching type, so
# stronger / more specific signals are listed before noisier generic ones
# (implementation detail last — its keywords are the most common).
# English needles match on word boundaries (case-insensitive); Chinese
# needles match as plain substrings (no word boundaries in Chinese).
# ---------------------------------------------------------------------------

_SIGNALS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        MemoryCardType.DECISION,
        (
            "decided",
            "decide to",
            "we agreed",
            "agreed",
            "final",
            "finalize",
            "finalized",
            "settled",
            "we will",
            "we'll",
            "let's use",
            "let's go with",
            "go with",
            "going with",
            "choose",
            "chose",
            "decision",
        ),
        ("决定", "定了", "最终", "就用", "方案", "采用"),
    ),
    (
        MemoryCardType.CONSTRAINT,
        (
            "must not",
            "must",
            "cannot",
            "can't",
            "requirement",
            "constraint",
            "avoid",
            "only if",
            "do not",
            "don't",
        ),
        ("必须", "不能", "不要", "限制", "要求", "只能", "避免"),
    ),
    (
        MemoryCardType.OPEN_QUESTION,
        (
            "open question",
            "unclear",
            "tbd",
            "not sure",
            "unsure",
            "decide later",
            "undecided",
        ),
        ("未定", "待确认", "不确定", "之后再定", "还没决定"),
    ),
    (
        MemoryCardType.PREFERENCE,
        (
            "prefer",
            "preference",
            "i like",
            "format",
            "style",
            "default to",
        ),
        ("偏好", "喜欢", "格式", "风格", "默认"),
    ),
    (
        MemoryCardType.TODO,
        (
            "todo",
            "to-do",
            "next step",
            "need to",
            "needs to",
            "follow up",
            "follow-up",
            "later",
            "implement next",
        ),
        ("下一步", "待办", "还要", "之后", "需要做"),
    ),
    (
        MemoryCardType.IMPLEMENTATION_DETAIL,
        (
            "implement",
            # "implement" won't match "implementation" under word boundaries
            # (trailing "ation" breaks \b), yet "Implementation detail:" is the
            # most natural phrasing — match it explicitly.
            "implementation",
            "code",
            "function",
            "class",
            "file path",
            "bug",
            "fix",
            "api",
            "cache",
            "queue",
        ),
        ("实现", "代码", "函数", "类", "文件", "bug", "修复", "接口", "缓存"),
    ),
)

# Strong markers bump confidence to "high" when present in the sentence.
_STRONG_MARKERS_EN = re.compile(
    r"\b(?:final|finalized|decided|decision|must|must not|cannot|requirement)\b",
    re.IGNORECASE,
)
_STRONG_MARKERS_ZH = ("必须", "决定", "最终", "不能")

# Which card types each source is allowed to produce. The assistant's final
# response is the source of truth for decisions/todos/implementation; user
# text is used mainly for topic/entities and for user-stated
# preferences/constraints/todos/questions.
_ASSISTANT_TYPES = frozenset(
    {
        MemoryCardType.DECISION,
        MemoryCardType.CONSTRAINT,
        MemoryCardType.OPEN_QUESTION,
        MemoryCardType.PREFERENCE,
        MemoryCardType.TODO,
        MemoryCardType.IMPLEMENTATION_DETAIL,
    }
)
_USER_TYPES = frozenset(
    {
        MemoryCardType.PREFERENCE,
        MemoryCardType.CONSTRAINT,
        MemoryCardType.TODO,
        MemoryCardType.OPEN_QUESTION,
    }
)

# Human-readable, search-friendly labels per type. Included in the formatted
# block so PR2/PR3 recall queries (which add terms like "final decision",
# "user preference", "implementation details") match stored cards by text.
_TYPE_LABELS: dict[str, str] = {
    MemoryCardType.DECISION: "decision; final decision; previous decision; agreed approach",
    MemoryCardType.PREFERENCE: "preference; user preference; preferred format; style",
    MemoryCardType.TODO: "todo; task; next step; open todo; status",
    MemoryCardType.CONSTRAINT: "constraint; requirement; must; restriction",
    MemoryCardType.IMPLEMENTATION_DETAIL: (
        "implementation detail; implementation details; constraints; code path"
    ),
    MemoryCardType.OPEN_QUESTION: "open question; unresolved; tbd; decide later",
}


def _compile_needles(needles: tuple[str, ...]) -> re.Pattern[str]:
    """Compile English needles into one word-boundary alternation regex."""
    alternation = "|".join(re.escape(n) for n in needles)
    return re.compile(r"\b(?:" + alternation + r")\b", re.IGNORECASE)

_SIGNAL_PATTERNS: tuple[tuple[str, re.Pattern[str], tuple[str, ...]], ...] = tuple(
    (card_type, _compile_needles(en), zh) for (card_type, en, zh) in _SIGNALS
)

# Sentence segmentation. An ASCII ``.``/``!``/``?`` only ends a sentence when
# followed by whitespace or end-of-text, so dotted identifiers, file paths,
# versions, and URLs (``agent/memory_manager.py``, ``api.example.com``,
# ``v1.2``) stay intact — they're exactly the content implementation-detail
# cards care about. CJK terminators (。！？) always split, and newlines act as
# separators (excluded from the body class). The sentence body is any run of
# non-terminator chars OR an ASCII terminator that is *not* a real boundary.
_SENTENCE_RE = re.compile(
    r"(?:[^.!?。！？\n]|[.!?](?!\s|$))+(?:[.!?](?=\s|$)|[。！？])?"
)
_WHITESPACE_RE = re.compile(r"\s+")

_MAX_SUMMARY_CHARS = 240
_MAX_TITLE_CHARS = 80
_MAX_ENTITIES_PER_CARD = 6


def _hash(text: str, length: int = 16) -> str:
    """Stable short hex digest (no raw text retained)."""
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:length]


def _normalized_topic_key(entities: list[str], title: str) -> str:
    """Deterministic topic key from entities (preferred) else title tokens."""
    if entities:
        parts = sorted({e.casefold().strip() for e in entities if e and e.strip()})
    else:
        parts = sorted(
            {t for t in re.findall(r"[a-z0-9]+|[一-鿿]+", (title or "").casefold())
             if len(t) >= 2}
        )
    return "|".join(p for p in parts if p)


def compute_conflict_group_id(
    card_type: str, entities: list[str], title: str
) -> str:
    """Deterministic conflict-group id from card type + normalized topic.

    Same type + same topic (entities, else title tokens) always yields the
    same group id, regardless of candidate search order. The id is a hash —
    no raw conversation text is exposed. Returns "" when there is no usable
    topic signal (so callers can decline to group).
    """
    topic = _normalized_topic_key(entities, title)
    if not topic:
        return ""
    return _hash((card_type or "") + "\x00" + topic, 12)


def _clean_for_cards(value: object, max_chars: int) -> str:
    """Sanitize raw turn content into bounded, card-safe text.

    Strips ``<memory-context>`` blocks, recalled-memory system notes, fenced
    code, and tool-ish XML spans; drops bracket-heavy blob lines; then bounds
    the total to ``max_chars``. ``None``/non-string inputs become "".
    """
    text = _content_to_text(value)
    if not text:
        return ""
    text = _MEMORY_CONTEXT_RE.sub(" ", text)
    text = _SYSTEM_NOTE_RE.sub(" ", text)
    text = _FENCED_CODE_RE.sub(" ", text)
    text = _XML_TOOLISH_RE.sub(" ", text)
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if (
            stripped.count("{")
            + stripped.count("}")
            + stripped.count("[")
            + stripped.count("]")
            > 24
        ):
            continue
        kept.append(stripped)
    cleaned = "\n".join(kept)
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned


def _is_question(sentence: str) -> bool:
    tail = sentence[-4:]
    return (
        sentence.endswith("?")
        or sentence.endswith("？")
        or "吗" in tail
        or "呢" in tail
    )


def _classify(sentence: str, allowed: frozenset[str]) -> str | None:
    """Return the first matching card type for a sentence, or None.

    Questions are only eligible to become open-question cards (a question is
    not a decision/constraint/etc.), and then only when an open-question
    keyword is present.
    """
    lowered = sentence.casefold()
    question = _is_question(sentence)
    for card_type, pattern, zh in _SIGNAL_PATTERNS:
        if card_type not in allowed:
            continue
        if question and card_type != MemoryCardType.OPEN_QUESTION:
            continue
        if pattern.search(lowered) or any(n in sentence for n in zh):
            return card_type
    return None


def _confidence_for(card_type: str, sentence: str) -> str:
    if card_type == MemoryCardType.OPEN_QUESTION:
        return "low"
    if _STRONG_MARKERS_EN.search(sentence) or any(
        m in sentence for m in _STRONG_MARKERS_ZH
    ):
        return "high"
    return "medium"


def _make_title(summary: str, entities: list[str]) -> str:
    if entities:
        title = "; ".join(entities[:2])
    else:
        title = " ".join(summary.split()[:8])
    title = _WHITESPACE_RE.sub(" ", title).strip()
    if len(title) > _MAX_TITLE_CHARS:
        title = title[:_MAX_TITLE_CHARS].rstrip()
    return title or summary[:_MAX_TITLE_CHARS].rstrip()


def _build_card(
    card_type: str,
    sentence: str,
    user_entities: list[str],
    session_id: str,
    turn_hash: str,
) -> MemoryCard:
    summary = _WHITESPACE_RE.sub(" ", sentence).strip()
    if len(summary) > _MAX_SUMMARY_CHARS:
        summary = summary[:_MAX_SUMMARY_CHARS].rstrip()

    sentence_entities = _extract_entities(sentence)
    entities: list[str] = []
    seen: set[str] = set()
    for value in (*sentence_entities, *user_entities):
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        entities.append(value)
        if len(entities) >= _MAX_ENTITIES_PER_CARD:
            break

    title = _make_title(summary, entities)
    status = (
        MemoryCardStatus.OPEN
        if card_type == MemoryCardType.OPEN_QUESTION
        else MemoryCardStatus.ACTIVE
    )
    confidence = _confidence_for(card_type, sentence)

    id_payload = "|".join(
        (
            card_type,
            _WHITESPACE_RE.sub(" ", title).casefold(),
            _WHITESPACE_RE.sub(" ", summary).casefold(),
            "|".join(e.casefold() for e in entities),
            _hash(session_id or "", 12),
        )
    )
    card_id = _hash(id_payload)

    return MemoryCard(
        card_id=card_id,
        type=card_type,
        status=status,
        title=title,
        summary=summary,
        entities=entities,
        confidence=confidence,
        source_session_id=session_id or "",
        source_turn_hash=turn_hash,
    )


def extract_memory_cards(
    user_content: object,
    assistant_content: object,
    *,
    session_id: str = "",
    max_cards: int = 5,
    max_chars: int = 2500,
) -> list[MemoryCard]:
    """Extract structured memory cards from a completed turn.

    Pure, deterministic, best-effort. ``None``/non-string inputs are handled
    gracefully (return ``[]`` rather than crash). Cards are deduplicated by
    ``card_id`` within the turn and capped at ``max_cards``. Assistant
    sentences are processed first (source of truth), so under the cap
    assistant-derived cards take priority.
    """
    max_cards = max(0, int(max_cards or 0))
    max_chars = max(1, int(max_chars or 1))
    if max_cards == 0:
        return []

    user_text = _clean_for_cards(user_content, max_chars)
    assistant_text = _clean_for_cards(assistant_content, max_chars)
    if not user_text and not assistant_text:
        return []

    turn_hash = _hash(user_text + "\x00" + assistant_text)
    user_entities = _extract_entities(user_text) if user_text else []

    cards: list[MemoryCard] = []
    seen_ids: set[str] = set()

    # Assistant first (source of truth), then user.
    for text, allowed in (
        (assistant_text, _ASSISTANT_TYPES),
        (user_text, _USER_TYPES),
    ):
        if not text:
            continue
        for match in _SENTENCE_RE.finditer(text):
            sentence = match.group(0).strip()
            if len(sentence) < 2:
                continue
            card_type = _classify(sentence, allowed)
            if card_type is None:
                continue
            card = _build_card(
                card_type, sentence, user_entities, session_id, turn_hash
            )
            if card.card_id in seen_ids:
                continue
            seen_ids.add(card.card_id)
            cards.append(card)
            if len(cards) >= max_cards:
                return cards
    return cards


def format_memory_cards_for_sync(
    cards: list[MemoryCard], *, max_chars: int = 2500
) -> str:
    """Format cards into a compact, search-friendly block for provider sync.

    Returns "" for an empty/falsy list. The output is bounded by
    ``max_chars`` (whole cards are dropped once the budget would be
    exceeded; the wrapper tags are always closed). The format intentionally
    surfaces ``type``/``status``/``title``/``summary``/``entities`` plus a
    ``labels`` line of recall-friendly phrases so PR2/PR3 recall queries
    match stored cards by text. It never includes raw conversation, memory
    context, or code blobs (the cards were already sanitized at extraction).
    """
    if not cards:
        return ""

    header = '<structured-memory-cards version="1">'
    footer = "</structured-memory-cards>"
    budget = max(1, int(max_chars or 1))

    lines: list[str] = []
    used = len(header) + 1 + len(footer)  # header + newline + footer
    for card in cards:
        entities = "; ".join(card.entities)
        labels = _TYPE_LABELS.get(card.type, card.type)
        parts = [
            f"- type: {card.type}",
            f"  card_id: {card.card_id}",
            f"  status: {card.status}",
            f"  title: {card.title}",
            f"  summary: {card.summary}",
            f"  entities: {entities}",
            f"  labels: {labels}",
            f"  confidence: {card.confidence}",
        ]
        # PR5 supersession fields — emitted only when present, so PR4 cards
        # are byte-for-byte unchanged apart from the new card_id line.
        if card.supersedes:
            parts.append("  supersedes: " + "; ".join(card.supersedes))
        if card.superseded_by:
            parts.append(f"  superseded_by: {card.superseded_by}")
        if card.conflict_group_id:
            parts.append(f"  conflict_group: {card.conflict_group_id}")
        parts.append(
            f"  source_session: {_hash(card.source_session_id or '', 12)}"
        )
        block = "\n".join(parts)
        if used + len(block) + 1 > budget:
            break
        lines.append(block)
        used += len(block) + 1

    if not lines:
        return ""
    return header + "\n" + "\n".join(lines) + "\n" + footer


# ---------------------------------------------------------------------------
# Parsing (PR5) — read structured-card blocks back out of recalled text.
# ---------------------------------------------------------------------------

@dataclass
class ParsedMemoryCard:
    """A structured card parsed from recalled/stored text (best-effort)."""

    card_id: str = ""
    type: str = ""
    status: str = ""
    title: str = ""
    summary: str = ""
    entities: list[str] = field(default_factory=list)
    labels: str = ""
    supersedes: list[str] = field(default_factory=list)
    superseded_by: str = ""
    conflict_group: str = ""


_CARDS_BLOCK_RE = re.compile(
    r"<structured-memory-cards\b[^>]*>([\s\S]*?)</structured-memory-cards>",
    re.IGNORECASE,
)
# Same block, but capturing the open/close tags too (for in-place filtering).
_CARDS_BLOCK_FULL_RE = re.compile(
    r"(<structured-memory-cards\b[^>]*>)([\s\S]*?)(</structured-memory-cards>)",
    re.IGNORECASE,
)
_PARSE_MAX_CHARS = 100_000


def _split_list(value: str) -> list[str]:
    return [p.strip() for p in value.split(";") if p.strip()]


def parse_memory_cards_from_text(text: object) -> list[ParsedMemoryCard]:
    """Parse PR4/PR5 structured-card blocks out of (recalled) text.

    Deterministic, dependency-free, and fail-CLOSED: any malformed or
    non-structured input yields ``[]`` rather than raising. Memory-context
    blocks are stripped first, and the input is length-bounded. Only text in
    the explicit ``<structured-memory-cards>`` wrapper is parsed — arbitrary
    conversation is never interpreted as a card.
    """
    try:
        raw = _content_to_text(text)
        if not raw:
            return []
        raw = _MEMORY_CONTEXT_RE.sub(" ", raw)
        if len(raw) > _PARSE_MAX_CHARS:
            raw = raw[:_PARSE_MAX_CHARS]

        cards: list[ParsedMemoryCard] = []
        for block_match in _CARDS_BLOCK_RE.finditer(raw):
            body = block_match.group(1)
            current: ParsedMemoryCard | None = None
            for line in body.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                is_new = stripped.startswith("- ")
                if is_new:
                    stripped = stripped[2:].strip()
                if ":" not in stripped:
                    continue
                key, _, value = stripped.partition(":")
                key = key.strip().casefold()
                value = value.strip()
                if is_new:
                    # A new card starts at the first "- <key>:" line.
                    if current is not None:
                        cards.append(current)
                    current = ParsedMemoryCard()
                if current is None:
                    # Indented line before any "- " delimiter — skip.
                    continue
                if key == "type":
                    current.type = value
                elif key == "card_id":
                    current.card_id = value
                elif key == "status":
                    current.status = value
                elif key == "title":
                    current.title = value
                elif key == "summary":
                    current.summary = value
                elif key == "entities":
                    current.entities = _split_list(value)
                elif key == "labels":
                    current.labels = value
                elif key == "supersedes":
                    current.supersedes = _split_list(value)
                elif key == "superseded_by":
                    current.superseded_by = value
                elif key == "conflict_group":
                    current.conflict_group = value
            if current is not None:
                cards.append(current)

        # Keep only chunks that actually looked like a card (had a type).
        return [c for c in cards if c.type]
    except Exception:
        return []


def _iter_card_chunks(body: str) -> list[list[str]]:
    """Split a card-block body into per-card line chunks (delimiter ``- ``)."""
    chunks: list[list[str]] = []
    current: list[str] = []
    for line in body.splitlines():
        if line.startswith("- "):
            if current:
                chunks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        chunks.append(current)
    return chunks


def _chunk_card_id(chunk: list[str]) -> str:
    for line in chunk:
        stripped = line.strip()
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        if stripped.casefold().startswith("card_id:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def filter_superseded_card_text(text: str, superseded_ids: set[str]) -> tuple[str, int]:
    """Drop superseded card chunks from structured-card blocks in ``text``.

    Returns ``(new_text, removed_count)``. Non-structured text is untouched;
    a block whose every card is superseded is removed entirely. Fail-open:
    on any error the original text is returned unchanged.
    """
    if not superseded_ids or not text or "<structured-memory-cards" not in text:
        return text, 0
    removed = 0

    def _repl(match: re.Match[str]) -> str:
        nonlocal removed
        open_tag, body, close_tag = match.group(1), match.group(2), match.group(3)
        kept: list[list[str]] = []
        for chunk in _iter_card_chunks(body):
            cid = _chunk_card_id(chunk)
            if cid and cid in superseded_ids:
                removed += 1
                continue
            kept.append(chunk)
        if not kept:
            return ""
        inner = "\n".join("\n".join(chunk) for chunk in kept)
        return open_tag + "\n" + inner + "\n" + close_tag

    try:
        new_text = _CARDS_BLOCK_FULL_RE.sub(_repl, text)
    except Exception:
        return text, 0
    return new_text, removed
