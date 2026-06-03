"""Deterministic structured-card supersession/conflict resolution (PR5).

When a new structured card clearly *overrides* a prior card about the same
topic, we record that append-only: the new card gains ``supersedes`` +
``conflict_group_id`` metadata and we emit a separate "superseded" marker
card. Old provider memories are never deleted or rewritten.

Design constraints (mirrors PR4):

- No LLM. Conflict detection is conservative, keyword/overlap based.
- No external dependencies.
- Fail-open / fail-closed: malformed candidates are ignored, never raised on.
- Default-off (gated by config at the call site).

A supersession is recorded only when ALL hold:
  1. compatible types (same type for decision/preference/constraint; todo only
     when explicitly done/replaced; decision may resolve an open_question);
  2. same topic (entity overlap >= min_entity_overlap, OR conflict_group
     match, OR strong title-token overlap);
  3. explicit override language in the new card (unless
     require_explicit_override is False).
Already-superseded or id-less candidates are skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agent.memory_cards import (
    MemoryCard,
    MemoryCardStatus,
    MemoryCardType,
    ParsedMemoryCard,
    _hash,
    compute_conflict_group_id,
    parse_memory_cards_from_text,
)


_CANDIDATE_QUERY_MAX_CHARS = 240


def build_candidate_query(card: MemoryCard, *, max_chars: int = _CANDIDATE_QUERY_MAX_CHARS) -> str:
    """Deterministic, search-friendly query to find prior cards on this topic.

    Shape: ``type: <type> status: active <entities/title> conflict_group: <g>
    structured-memory-cards``. Bounded; contains no raw conversation text
    beyond the card's already-sanitized entities/title.
    """
    terms: list[str] = [f"type: {card.type}", "status: active"]
    if card.entities:
        terms.append(" ".join(card.entities[:6]))
    elif card.title:
        terms.append(card.title)
    group = compute_conflict_group_id(card.type, card.entities, card.title)
    if group:
        terms.append(f"conflict_group: {group}")
    terms.append("structured-memory-cards")
    query = " ".join(t for t in terms if t).strip()
    return query[: max(1, int(max_chars or 1))]


@dataclass
class ConflictResolutionResult:
    updated_new_cards: list[MemoryCard] = field(default_factory=list)
    superseded_marker_cards: list[MemoryCard] = field(default_factory=list)
    # Metadata counts only (safe to log) — never any card text.
    candidates_parsed: int = 0
    superseded_count: int = 0
    marker_count: int = 0


_OVERRIDE_EN = (
    "instead",
    "replace",
    "replaces",
    "replaced",
    "change to",
    "changed to",
    "switch to",
    "switching to",
    "no longer",
    "from now on",
    "override",
    "overrides",
    "supersede",
    "supersedes",
    "final decision is",
    "actually use",
    "use instead",
    "don't use",
    "do not use",
)
_OVERRIDE_ZH = (
    "改成", "换成", "不用", "不要", "不再", "覆盖", "替代", "取代",
    "从现在开始", "最终用", "其实用",
)

_DONE_EN = ("done", "completed", "complete", "finished", "replaced", "resolved")
_DONE_ZH = ("完成", "做完", "已完成", "搞定")

# open_question -> decision resolution requires EXPLICIT resolved/decided
# language. Deliberately excludes bare "use"/"we will" (a normal decision
# sentence saying "use X" must NOT silently resolve an open question).
_RESOLVED_EN = (
    "resolved",
    "decided",
    "final decision",
    "no longer open",
    "answer is",
    "settled",
    "tbd resolved",
)
_RESOLVED_ZH = (
    "已解决", "解决了", "已决定", "最终决定", "不再待定", "答案是", "定了",
)

_TITLE_TOKEN_RE = re.compile(r"[a-z0-9]+|[一-鿿]+")
_MAX_TITLE_CHARS = 80

# Generic/scaffolding tokens that must not count toward topic overlap — they
# appear in many unrelated card titles and would cause false-positive
# supersession (e.g. two unrelated decisions sharing "the"/"use"/"decision").
_TITLE_STOPWORDS = frozenset(
    "the a an of to for and or we i you it is are was do did decision decided "
    "use using used set change changed switch instead final status type card "
    "this that with on in by".split()
)

# Generic topic words that must NOT, by themselves, satisfy the entity/topic
# gate. Two cards sharing only "API"/"UI"/"cache" are not the same topic. A
# multi-word entity ("Telegram approval cards") is matched whole and is NOT in
# this set, so specific entities still work.
_GENERIC_ENTITIES = frozenset(
    "api ui ux http https json xml html cli sdk db sql url uri id uuid cache "
    "queue bot app apps card cards button buttons page pages screen screens "
    "code data server client error test tests config system service tool "
    "file files function class method endpoint request response".split()
)


def _compile(needles: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(
        r"\b(?:" + "|".join(re.escape(n) for n in needles) + r")\b", re.IGNORECASE
    )


_OVERRIDE_EN_RE = _compile(_OVERRIDE_EN)
_DONE_EN_RE = _compile(_DONE_EN)
_RESOLVED_EN_RE = _compile(_RESOLVED_EN)


def _has(en_re: re.Pattern[str], zh: tuple[str, ...], text: str) -> bool:
    if not text:
        return False
    return bool(en_re.search(text)) or any(n in text for n in zh)


def _new_card_text(card: MemoryCard) -> str:
    return (card.summary or "") + "\n" + (card.title or "")


def _title_tokens(title: str) -> set[str]:
    return {
        t
        for t in _TITLE_TOKEN_RE.findall((title or "").casefold())
        if len(t) >= 2 and t not in _TITLE_STOPWORDS and t not in _GENERIC_ENTITIES
    }


def _specific_entities(entities: list[str]) -> set[str]:
    """Casefolded entity set with generic topic words removed.

    Generic entities (API, UI, cache, ...) must not satisfy the topic gate by
    themselves; multi-word specific entities are kept whole.
    """
    return {
        e.casefold()
        for e in entities
        if e and e.casefold() not in _GENERIC_ENTITIES
    }


def _topic_matches(
    new_card: MemoryCard,
    new_group: str,
    cand: ParsedMemoryCard,
    min_entity_overlap: int,
) -> bool:
    # Entity overlap is the primary signal — but only on SPECIFIC entities, so
    # two cards sharing just "API"/"UI" are not treated as the same topic.
    ne = _specific_entities(new_card.entities)
    ce = _specific_entities(cand.entities)
    if ne and ce and len(ne & ce) >= max(1, min_entity_overlap):
        return True
    # Exact conflict-group hash match (both must have one set).
    if new_group and cand.conflict_group and new_group == cand.conflict_group:
        return True
    # Title-token overlap is a conservative LAST resort: only when NEITHER
    # card carries a specific entity (so it can't hijack entity-bearing cards),
    # and only on stopword/generic-filtered tokens with a 2-token floor.
    if not ne and not ce:
        nt = _title_tokens(new_card.title)
        ct = _title_tokens(cand.title)
        if nt and ct and len(nt & ct) >= 2:
            return True
    return False


def _is_supersession(
    new_card: MemoryCard,
    new_group: str,
    cand: ParsedMemoryCard,
    *,
    require_explicit_override: bool,
    min_entity_overlap: int,
) -> bool:
    # Conservative gates — any failure means "not a conflict".
    if not cand.card_id:
        return False  # can't reference an id-less / malformed candidate
    if cand.status == MemoryCardStatus.SUPERSEDED:
        return False  # never re-supersede a tombstone
    if cand.card_id == new_card.card_id:
        return False  # don't match self
    if not _topic_matches(new_card, new_group, cand, min_entity_overlap):
        return False

    text = _new_card_text(new_card)
    override = _has(_OVERRIDE_EN_RE, _OVERRIDE_ZH, text)
    ot, nt = cand.type, new_card.type

    if nt == ot:
        if ot == MemoryCardType.TODO:
            # A todo supersedes a prior todo only when explicitly done/replaced.
            return _has(_DONE_EN_RE, _DONE_ZH, text) or override
        if ot in (
            MemoryCardType.DECISION,
            MemoryCardType.PREFERENCE,
            MemoryCardType.CONSTRAINT,
        ):
            return override or not require_explicit_override
        # open_question / implementation_detail same-type: not supersedable.
        return False

    if nt == MemoryCardType.DECISION and ot == MemoryCardType.OPEN_QUESTION:
        # A decision resolves an open question only with explicit language.
        return _has(_RESOLVED_EN_RE, _RESOLVED_ZH, text) or override

    return False


def _make_marker(cand: ParsedMemoryCard, new_card: MemoryCard, group: str) -> MemoryCard:
    title = ("Superseded: " + (cand.title or cand.card_id))[: _MAX_TITLE_CHARS + 12]
    return MemoryCard(
        card_id=_hash("superseded|" + cand.card_id + "|" + new_card.card_id, 16),
        type=cand.type,
        status=MemoryCardStatus.SUPERSEDED,
        # Fixed template — deliberately excludes the old card's raw summary.
        title=title,
        summary="This prior card was superseded by " + new_card.card_id + ".",
        entities=list(cand.entities),
        confidence="medium",
        source_session_id=new_card.source_session_id,
        source_turn_hash=new_card.source_turn_hash,
        # Carry the OLD card id so a marker-only recall (without the active new
        # card) can still suppress the old card during merge filtering.
        supersedes=[cand.card_id],
        superseded_by=new_card.card_id,
        conflict_group_id=group or (cand.conflict_group or None),
    )


def resolve_card_conflicts(
    new_cards: list[MemoryCard],
    candidate_texts: list[str],
    *,
    require_explicit_override: bool = True,
    min_entity_overlap: int = 1,
    max_candidates: int = 8,
) -> ConflictResolutionResult:
    """Detect deterministic supersessions and return append-only updates.

    ``new_cards`` are mutated in place (supersedes/conflict_group_id set) and
    returned in ``updated_new_cards``; ``superseded_marker_cards`` holds the
    new tombstone cards. Old candidate cards are never modified. The result
    carries only safe counts for logging.
    """
    result = ConflictResolutionResult(updated_new_cards=list(new_cards or []))
    if not new_cards or not candidate_texts:
        return result

    max_candidates = max(0, int(max_candidates or 0))
    if max_candidates == 0:
        return result

    # Parse all candidate texts (fail-closed), dedupe by card_id (the same
    # prior card can appear in several candidate results), then cap.
    parsed: list[ParsedMemoryCard] = []
    seen_ids: set[str] = set()
    for text in candidate_texts:
        for card in parse_memory_cards_from_text(text):
            if card.card_id and card.card_id in seen_ids:
                continue
            if card.card_id:
                seen_ids.add(card.card_id)
            parsed.append(card)
    parsed = parsed[:max_candidates]
    result.candidates_parsed = len(parsed)
    if not parsed:
        return result

    markers_by_old: dict[str, MemoryCard] = {}
    superseded_links = 0

    for new_card in new_cards:
        # implementation_detail / open_question new cards can't supersede.
        if new_card.type not in (
            MemoryCardType.DECISION,
            MemoryCardType.PREFERENCE,
            MemoryCardType.CONSTRAINT,
            MemoryCardType.TODO,
        ):
            continue
        new_group = compute_conflict_group_id(
            new_card.type, new_card.entities, new_card.title
        )
        for cand in parsed:
            if not _is_supersession(
                new_card,
                new_group,
                cand,
                require_explicit_override=require_explicit_override,
                min_entity_overlap=min_entity_overlap,
            ):
                continue
            if cand.card_id not in new_card.supersedes:
                new_card.supersedes.append(cand.card_id)
            if new_group:
                new_card.conflict_group_id = new_group
            superseded_links += 1
            if cand.card_id not in markers_by_old:
                markers_by_old[cand.card_id] = _make_marker(
                    cand, new_card, new_group
                )

    result.superseded_marker_cards = list(markers_by_old.values())
    result.superseded_count = superseded_links
    result.marker_count = len(result.superseded_marker_cards)
    return result
