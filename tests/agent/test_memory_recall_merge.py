"""Tests for deterministic multi-query recall merge/dedupe."""

from agent.memory_recall_merge import MergedRecall, merge_recall_results


def test_empty_input_returns_empty():
    merged = merge_recall_results([])
    assert isinstance(merged, MergedRecall)
    assert merged.text == ""
    assert merged.output_sections == 0
    assert merged.input_sections == 0
    assert merged.raw_chars == 0
    assert merged.final_chars == 0
    assert merged.removed_chars == 0


def test_all_blank_results_return_empty():
    merged = merge_recall_results(["", "   ", "\n\n"])
    assert merged.text == ""
    assert merged.output_sections == 0


def test_duplicate_full_results_dedupe():
    a = "- alpha fact\n\n- beta fact"
    merged = merge_recall_results([a, a])
    assert merged.text == a
    assert merged.input_sections == 4
    assert merged.output_sections == 2
    assert merged.removed_chars == len(a)  # the second copy was removed


def test_duplicate_sections_dedupe_and_preserve_priority_order():
    merged = merge_recall_results(
        ["- alpha\n\n- beta", "- beta\n\n- gamma"]
    )
    assert merged.text == "- alpha\n\n- beta\n\n- gamma"
    assert merged.output_sections == 3


def test_whitespace_normalized_duplicates_dedupe_but_keep_readable_text():
    merged = merge_recall_results(["- alpha   value", "- alpha value"])
    # First (readable) form is kept; the whitespace variant is treated as dup.
    assert merged.text == "- alpha   value"
    assert merged.output_sections == 1


def test_max_total_chars_respected_stops_adding_sections():
    merged = merge_recall_results(["x" * 100, "y" * 100], max_total_chars=120)
    assert merged.final_chars <= 120
    assert merged.text == "x" * 100  # second section would exceed the budget


def test_oversized_first_section_is_truncated_to_budget():
    merged = merge_recall_results(["z" * 500], max_total_chars=50)
    assert merged.final_chars == 50
    assert merged.text == "z" * 50


def test_priority_order_preserved_across_results():
    merged = merge_recall_results(["- first", "- second", "- third"])
    assert merged.text == "- first\n\n- second\n\n- third"


def test_crlf_blank_lines_split_and_dedupe_against_lf():
    crlf = "- alpha\r\n\r\n- beta"
    lf = "- alpha\n\n- gamma"
    merged = merge_recall_results([crlf, lf])
    # CRLF result splits into sections; "- alpha" dedupes against the LF copy.
    assert merged.output_sections == 3
    assert "- beta" in merged.text
    assert "- gamma" in merged.text
    # No surviving blank-line CRLF separator inside the merged block.
    assert "\r\n\r\n" not in merged.text


def test_unicode_preserved():
    merged = merge_recall_results(["决定使用紧凑按钮", "决定使用紧凑按钮", "移动端布局"])
    assert merged.text == "决定使用紧凑按钮\n\n移动端布局"
    assert merged.output_sections == 2


def test_non_string_results_are_ignored():
    merged = merge_recall_results([None, "- ok", 123])  # type: ignore[list-item]
    assert merged.text == "- ok"
    assert merged.output_sections == 1


# ---------------------------------------------------------------------------
# PR5: supersession filter
# ---------------------------------------------------------------------------

from agent.memory_cards import MemoryCard, format_memory_cards_for_sync  # noqa: E402


def _old():
    return MemoryCard(
        card_id="OLDID1", type="decision", status="active",
        title="Telegram cards", summary="Use TWOROW buttons.",
        entities=["Telegram cards"], source_session_id="s",
    )


def _new():
    return MemoryCard(
        card_id="NEWID2", type="decision", status="active",
        title="Telegram cards", summary="ONEROW instead.",
        entities=["Telegram cards"], supersedes=["OLDID1"],
        conflict_group_id="g1", source_session_id="s",
    )


def test_filter_off_preserves_both():
    out = merge_recall_results(
        [format_memory_cards_for_sync([_old()]),
         format_memory_cards_for_sync([_new()])],
        suppress_superseded=False,
    )
    assert "TWOROW" in out.text
    assert "ONEROW" in out.text
    assert out.suppressed_card_count == 0


def test_filter_on_suppresses_old_keeps_new():
    out = merge_recall_results(
        [format_memory_cards_for_sync([_old()]),
         format_memory_cards_for_sync([_new()])],
        suppress_superseded=True,
    )
    assert "TWOROW" not in out.text  # old card body gone
    assert "  card_id: OLDID1" not in out.text  # old chunk removed
    assert "ONEROW" in out.text  # new card kept
    assert out.suppressed_card_count == 1
    assert out.parsed_card_count == 2


def test_filter_on_suppresses_via_status_superseded_marker():
    marker = MemoryCard(
        card_id="MARK1", type="decision", status="superseded",
        title="Superseded: Telegram cards",
        summary="This prior card was superseded by NEWID2.",
        entities=["Telegram cards"], superseded_by="NEWID2",
        source_session_id="s",
    )
    out = merge_recall_results(
        [format_memory_cards_for_sync([marker])],
        suppress_superseded=True,
    )
    # The marker (status superseded) is itself suppressed.
    assert "MARK1" not in out.text
    assert out.suppressed_card_count == 1


def test_filter_on_old_alone_preserved():
    out = merge_recall_results(
        [format_memory_cards_for_sync([_old()])],
        suppress_superseded=True,
    )
    assert "TWOROW" in out.text
    assert out.suppressed_card_count == 0


def test_filter_on_non_structured_text_preserved():
    out = merge_recall_results(
        ["plain memory note about cats and dogs"],
        suppress_superseded=True,
    )
    assert "cats and dogs" in out.text


def test_filter_on_malformed_card_fails_open():
    text = "<structured-memory-cards>\nnonsense\n</structured-memory-cards>"
    out = merge_recall_results([text], suppress_superseded=True)
    # No crash; nothing falsely suppressed.
    assert isinstance(out, MergedRecall)
    assert out.suppressed_card_count == 0


def test_filter_on_unicode_preserved():
    old = MemoryCard(
        card_id="OLDU", type="decision", status="active", title="审批卡片",
        summary="就用双行。", entities=["审批卡片"], source_session_id="s",
    )
    new = MemoryCard(
        card_id="NEWU", type="decision", status="active", title="审批卡片",
        summary="改成单行。", entities=["审批卡片"], supersedes=["OLDU"],
        source_session_id="s",
    )
    out = merge_recall_results(
        [format_memory_cards_for_sync([old]),
         format_memory_cards_for_sync([new])],
        suppress_superseded=True,
    )
    assert "单行" in out.text       # new kept
    assert "双行" not in out.text   # old suppressed


def test_filter_on_respects_max_total_chars():
    out = merge_recall_results(
        [format_memory_cards_for_sync([_old()]),
         format_memory_cards_for_sync([_new()])],
        max_total_chars=120,
        suppress_superseded=True,
    )
    assert len(out.text) <= 120


def test_filter_marker_only_recall_suppresses_old_card():
    # PR5 fixup 5: a superseded marker carries the OLD card id in supersedes,
    # so the old card is suppressed even when the active new card is NOT in the
    # recalled set (only the old card + its marker are).
    marker = MemoryCard(
        card_id="MARK1", type="decision", status="superseded",
        title="Superseded: Telegram cards",
        summary="This prior card was superseded by NEWID2.",
        entities=["Telegram cards"], supersedes=["OLDID1"],
        superseded_by="NEWID2", source_session_id="s",
    )
    out = merge_recall_results(
        [format_memory_cards_for_sync([_old()]),
         format_memory_cards_for_sync([marker])],
        suppress_superseded=True,
    )
    assert "TWOROW" not in out.text          # old card suppressed via marker
    assert "  card_id: OLDID1" not in out.text
    assert "  card_id: MARK1" not in out.text  # marker (status superseded) too
    assert out.suppressed_card_count == 2
