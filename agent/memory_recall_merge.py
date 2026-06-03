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
) -> MergedRecall:
    """Merge per-subquery recall texts into one deduped, bounded block.

    ``results`` is consumed in priority order. Returns an empty-text
    :class:`MergedRecall` when every input is empty/blank.
    """
    max_total_chars = max(1, int(max_total_chars or 1))
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
                    # prefix rather than dropping recall entirely.
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
    )
