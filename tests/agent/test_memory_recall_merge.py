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
