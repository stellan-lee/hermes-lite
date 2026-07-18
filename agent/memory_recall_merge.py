"""Deterministic merge/dedupe for multi-query recall results.

Multi-query recall retrieves memory text for several subqueries and needs to
fold the (often overlapping) results into a single block before injection.
This module does that with no LLM and no external dependencies:

- exact-duplicate full results collapse (a result is a sequence of sections),
- duplicate sections (split on blank lines) are dropped,
- whitespace is normalized only for *comparison* — the readable original text
  is preserved in the output,
- priority order (the order results are passed in) is preserved,
- the merged text is bounded by ``max_total_chars``.

The returned :class:`MergedRecall` also carries small, non-sensitive counters
for debug logging and tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Split on a run of one-or-more blank lines (a line that is empty or only
# whitespace). Keeps single newlines inside a section intact. CRLF-aware so
# stored memory using "\r\n" still splits and dedupes against "\n" content.
_SECTION_SPLIT_RE = re.compile(r"(?:\r?\n)[ \t]*(?:\r?\n)+")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class MergedRecall:
    text: str
    input_sections: int
    output_sections: int
    raw_chars: int
    final_chars: int
    # Gross raw→final char delta (dedupe + budget drop + first-section
    # truncation combined), for debug logging only — not dedupe volume alone.
    removed_chars: int
    # PR5 supersession-filter metadata (0 unless suppress_superseded=True).
    parsed_card_count: int = 0
    suppressed_card_count: int = 0
    # Card-level dedupe metadata: cards dropped because the same card_id was
    # already emitted by an earlier (sub)query result.
    deduped_card_count: int = 0


def _collect_superseded_ids(results: list[str]) -> tuple[set[str], int]:
    """Parse structured cards across all results and collect superseded ids.

    An id is "superseded" if it appears in any active card's ``supersedes``
    list, or it is the id of a card whose status is ``superseded`` (a marker).
    Returns ``(superseded_ids, parsed_card_count)``. Fail-closed.
    """
    from agent.memory_cards import parse_memory_cards_from_text

    joined = "\n\n".join(r for r in results if isinstance(r, str))
    parsed = parse_memory_cards_from_text(joined)
    superseded: set[str] = set()
    for card in parsed:
        for old_id in card.supersedes:
            if old_id:
                superseded.add(old_id)
        if card.status == "superseded" and card.card_id:
            superseded.add(card.card_id)
    return superseded, len(parsed)


def _split_sections(text: str) -> list[str]:
    """Split a result into non-empty, stripped sections on blank-line breaks."""
    if not text or not text.strip():
        return []
    return [s.strip() for s in _SECTION_SPLIT_RE.split(text) if s.strip()]


def _normalize_for_compare(section: str) -> str:
    """Whitespace-collapsed key for duplicate detection (comparison only)."""
    return _WHITESPACE_RE.sub(" ", section).strip()


def merge_recall_results(
    results: list[str],
    *,
    max_total_chars: int = 6000,
    suppress_superseded: bool = False,
) -> MergedRecall:
    """Merge per-subquery recall texts into one deduped, bounded block.

    ``results`` is consumed in priority order. Returns an empty-text
    :class:`MergedRecall` when every input is empty/blank.

    When ``suppress_superseded`` is True (PR5, default off), structured cards
    whose ids are marked superseded — by an active card's ``supersedes`` list
    or a ``status: superseded`` marker — are dropped from the merged output
    before dedupe/bounding. Non-structured text and active/newer cards are
    preserved; parsing failures fail open (nothing suppressed).
    """
    max_total_chars = max(1, int(max_total_chars or 1))

    parsed_card_count = 0
    suppressed_card_count = 0
    if suppress_superseded and results:
        try:
            superseded_ids, parsed_card_count = _collect_superseded_ids(results)
            if superseded_ids:
                from agent.memory_cards import filter_superseded_card_text

                filtered: list[str] = []
                for r in results:
                    if isinstance(r, str):
                        new_r, removed = filter_superseded_card_text(
                            r, superseded_ids
                        )
                        suppressed_card_count += removed
                        filtered.append(new_r)
                    else:
                        filtered.append(r)
                results = filtered
        except Exception:
            parsed_card_count = 0
            suppressed_card_count = 0

    # Card-level dedupe across results (keep first occurrence of each card_id).
    # Runs BEFORE budget accounting so duplicate cards don't consume
    # max_total_chars and crowd out distinct content. Section dedupe below only
    # collapses byte-identical blocks, which misses cards repeated across
    # non-identical blocks from different subqueries.
    deduped_card_count = 0
    if results:
        try:
            from agent.memory_cards import dedupe_cards_in_text

            seen_card_ids: set[str] = set()
            deduped: list[str] = []
            for r in results:
                if isinstance(r, str):
                    new_r, dropped = dedupe_cards_in_text(r, seen_card_ids)
                    deduped_card_count += dropped
                    deduped.append(new_r)
                else:
                    deduped.append(r)
            results = deduped
        except Exception:
            deduped_card_count = 0

    raw_chars = sum(len(r) for r in results if isinstance(r, str))

    input_sections = 0
    out_sections: list[str] = []
    seen: set[str] = set()
    total = 0
    truncated = False

    for result in results:
        if not isinstance(result, str):
            continue
        if truncated:
            break
        for section in _split_sections(result):
            input_sections += 1
            key = _normalize_for_compare(section)
            if not key or key in seen:
                continue
            sep_len = 2 if out_sections else 0  # "\n\n" between sections
            projected = total + sep_len + len(section)
            if projected > max_total_chars:
                if not out_sections:
                    # First section alone exceeds the budget: keep a readable
                    # prefix rather than dropping recall entirely. A structured-
                    # card block must NOT be raw-clipped (that yields an
                    # unclosed <structured-memory-cards> tag and a half-card
                    # that the model mis-reads and that fails to re-parse);
                    # clip it at a whole-card boundary with a valid close tag,
                    # or drop it if not even one card fits.
                    if "<structured-memory-cards" in section.lower():
                        from agent.memory_cards import clip_cards_block_to_budget

                        clipped = clip_cards_block_to_budget(section, max_total_chars)
                    else:
                        clipped = section[:max_total_chars].rstrip()
                    if clipped:
                        out_sections.append(clipped)
                        seen.add(key)
                        total = len(clipped)
                truncated = True
                break
            seen.add(key)
            out_sections.append(section)
            total = projected

    text = "\n\n".join(out_sections)
    final_chars = len(text)
    return MergedRecall(
        text=text,
        input_sections=input_sections,
        output_sections=len(out_sections),
        raw_chars=raw_chars,
        final_chars=final_chars,
        removed_chars=max(0, raw_chars - final_chars),
        parsed_card_count=parsed_card_count,
        suppressed_card_count=suppressed_card_count,
        deduped_card_count=deduped_card_count,
    )
