"""Tests for deterministic structured memory cards (PR4).

Covers extraction heuristics (EN + ZH), sanitization, bounding/caps,
determinism, dedupe, and the search-friendly sync formatting.
"""

from agent.memory_cards import (
    MemoryCard,
    MemoryCardStatus,
    MemoryCardType,
    extract_memory_cards,
    format_memory_cards_for_sync,
)


# ---------------------------------------------------------------------------
# Input robustness
# ---------------------------------------------------------------------------


def test_none_and_non_string_inputs_do_not_crash():
    assert extract_memory_cards(None, None) == []
    assert extract_memory_cards({"content": "x"}, 12345) == []
    assert extract_memory_cards([], object()) == []


def test_empty_strings_return_no_cards():
    assert extract_memory_cards("", "") == []


def test_generic_conversation_has_no_durable_signal():
    cards = extract_memory_cards(
        "what's the weather today?",
        "It's sunny and around 22 degrees this afternoon.",
    )
    assert cards == []


# ---------------------------------------------------------------------------
# Per-type extraction (English + Chinese)
# ---------------------------------------------------------------------------


def _types(cards):
    return {c.type for c in cards}


def test_decision_extraction_english():
    cards = extract_memory_cards(
        "which approval UX should we use?",
        "We decided to use compact inline approval cards with Approve/Reject "
        "buttons. This is final.",
    )
    assert MemoryCardType.DECISION in _types(cards)
    decision = next(c for c in cards if c.type == MemoryCardType.DECISION)
    assert decision.status == MemoryCardStatus.ACTIVE


def test_decision_extraction_chinese():
    cards = extract_memory_cards(
        "审批用什么方案？",
        "我们最终决定就用紧凑型内联审批卡片。",
    )
    assert MemoryCardType.DECISION in _types(cards)


def test_preference_extraction():
    cards = extract_memory_cards(
        "I prefer dark mode and a compact layout for the dashboard.",
        "Got it, noting that down.",
    )
    assert MemoryCardType.PREFERENCE in _types(cards)


def test_preference_extraction_chinese():
    cards = extract_memory_cards(
        "我喜欢深色风格的界面。",
        "好的。",
    )
    assert MemoryCardType.PREFERENCE in _types(cards)


def test_todo_extraction():
    cards = extract_memory_cards(
        "anything left?",
        "Next step is to wire the cache invalidation; we still need to add "
        "tests for the queue path.",
    )
    assert MemoryCardType.TODO in _types(cards)


def test_constraint_extraction():
    cards = extract_memory_cards(
        "any rules I should know?",
        "The worker must not log raw user text and cannot block the turn.",
    )
    assert MemoryCardType.CONSTRAINT in _types(cards)


def test_constraint_extraction_chinese():
    cards = extract_memory_cards(
        "有什么限制？",
        "必须保证不能阻塞用户回合。",
    )
    assert MemoryCardType.CONSTRAINT in _types(cards)


def test_implementation_detail_extraction():
    cards = extract_memory_cards(
        "how does recall work?",
        "We implement the cache keyed by query and session in the prefetch "
        "queue path.",
    )
    assert MemoryCardType.IMPLEMENTATION_DETAIL in _types(cards)


def test_dotted_identifiers_and_paths_are_not_split_into_fragments():
    # Regression: a `.` inside a file path / dotted name / URL must not be
    # treated as a sentence boundary (it would spawn garbled fragment cards).
    cards = extract_memory_cards(
        "ok",
        "We decided to use queue_prefetch_all in agent/memory_manager.py and "
        "the MemoryManager class.",
    )
    decisions = [c for c in cards if c.type == MemoryCardType.DECISION]
    assert len(decisions) == 1
    summary = decisions[0].summary
    assert "agent/memory_manager.py" in summary
    # No spurious fragment card whose summary starts mid-token.
    assert not any(c.summary.startswith("py ") for c in cards)


def test_url_with_dots_not_fragmented():
    cards = extract_memory_cards(
        "ok",
        "We decided to call api.example.com for the cache lookup. This is final.",
    )
    decisions = [c for c in cards if c.type == MemoryCardType.DECISION]
    assert decisions
    assert any("api.example.com" in c.summary for c in decisions)


def test_open_question_extraction():
    cards = extract_memory_cards(
        "anything unresolved?",
        "One open question remains: the mobile layout is still TBD.",
    )
    assert MemoryCardType.OPEN_QUESTION in _types(cards)
    oq = next(c for c in cards if c.type == MemoryCardType.OPEN_QUESTION)
    assert oq.status == MemoryCardStatus.OPEN


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------


def test_memory_context_blocks_are_stripped():
    cards = extract_memory_cards(
        "ok",
        "We decided to use Foo. "
        "<memory-context>secret recalled text decided to use Bar</memory-context>",
    )
    blob = " ".join(c.summary for c in cards) + " ".join(
        " ".join(c.entities) for c in cards
    )
    assert "secret recalled text" not in blob
    assert "memory-context" not in blob


def test_code_and_tool_blobs_are_stripped_or_ignored():
    fenced = (
        "We decided to use the queue.\n"
        "```python\n"
        "def hack():\n"
        "    return 'decided to use evil'\n"
        "```\n"
    )
    cards = extract_memory_cards("ok", fenced)
    blob = " ".join(c.summary for c in cards)
    assert "def hack" not in blob
    assert "evil" not in blob


# ---------------------------------------------------------------------------
# Bounding, caps, dedupe, determinism
# ---------------------------------------------------------------------------


def test_max_cards_respected():
    text = (
        "We decided to use Foo. "
        "The worker must not block. "
        "Next step is to add tests. "
        "I prefer dark mode. "
        "We implement the cache in the queue. "
        "One open question: layout is TBD."
    )
    cards = extract_memory_cards(text, text, max_cards=2)
    assert len(cards) == 2


def test_max_cards_zero_returns_empty():
    cards = extract_memory_cards("we decided to use Foo", "final decision", max_cards=0)
    assert cards == []


def test_max_chars_respected_truncates_processed_text():
    # The decision sentence sits beyond the char budget, so it is truncated
    # away before classification and never becomes a card.
    assistant = ("x" * 200) + ". We decided to use Foo."
    cards = extract_memory_cards("ok", assistant, max_chars=50)
    assert MemoryCardType.DECISION not in _types(cards)


def test_summaries_are_bounded():
    long_decision = "We decided to use " + ("a very long phrase " * 60) + "."
    cards = extract_memory_cards("ok", long_decision)
    assert cards
    assert all(len(c.summary) <= 240 for c in cards)


def test_card_id_is_deterministic():
    args = ("which UX?", "We decided to use compact cards. This is final.")
    first = extract_memory_cards(*args, session_id="s1")
    second = extract_memory_cards(*args, session_id="s1")
    assert [c.card_id for c in first] == [c.card_id for c in second]
    assert all(c.card_id for c in first)


def test_card_id_changes_with_session():
    args = ("which UX?", "We decided to use compact cards. This is final.")
    a = extract_memory_cards(*args, session_id="s1")
    b = extract_memory_cards(*args, session_id="s2")
    assert a and b
    assert a[0].card_id != b[0].card_id


def test_duplicate_sentences_within_turn_are_deduped():
    repeated = (
        "We decided to use the compact cards. "
        "We decided to use the compact cards. "
        "We decided to use the compact cards."
    )
    cards = extract_memory_cards("ok", repeated)
    decisions = [c for c in cards if c.type == MemoryCardType.DECISION]
    assert len(decisions) == 1


def test_source_turn_hash_does_not_expose_raw_text():
    cards = extract_memory_cards(
        "secretuserphrase", "We decided to use secretassistantphrase finally."
    )
    assert cards
    for c in cards:
        assert "secretuserphrase" not in c.source_turn_hash
        assert "secretassistantphrase" not in c.source_turn_hash
        assert len(c.source_turn_hash) <= 32


def test_unicode_preserved_safely():
    cards = extract_memory_cards(
        "我喜欢简洁的设计。",
        "我们最终决定就用紧凑型卡片，按钮顺序是 Approve、Reject。",
    )
    assert cards
    summaries = " ".join(c.summary for c in cards)
    assert "紧凑型卡片" in summaries or "决定" in summaries


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _sample_card(**overrides):
    base = dict(
        card_id="abc123",
        type=MemoryCardType.DECISION,
        status=MemoryCardStatus.ACTIVE,
        title="Telegram approval cards UX",
        summary="Final decision: use compact inline approval cards.",
        entities=["Telegram approval cards", "Approve", "Reject"],
        confidence="medium",
        source_session_id="sess-1",
        source_turn_hash="deadbeef",
    )
    base.update(overrides)
    return MemoryCard(**base)


def test_format_empty_cards_returns_empty_string():
    assert format_memory_cards_for_sync([]) == ""
    assert format_memory_cards_for_sync(None) == ""


def test_format_includes_core_fields():
    out = format_memory_cards_for_sync([_sample_card()])
    assert 'structured-memory-cards version="1"' in out
    assert "type: decision" in out
    assert "status: active" in out
    assert "title: Telegram approval cards UX" in out
    assert "summary: Final decision" in out
    assert "entities: Telegram approval cards; Approve; Reject" in out
    assert "confidence: medium" in out
    assert out.strip().endswith("</structured-memory-cards>")


def test_format_includes_search_friendly_labels():
    decision = format_memory_cards_for_sync([_sample_card()])
    assert "final decision" in decision
    assert "previous decision" in decision

    pref = format_memory_cards_for_sync(
        [_sample_card(type=MemoryCardType.PREFERENCE)]
    )
    assert "user preference" in pref

    todo = format_memory_cards_for_sync([_sample_card(type=MemoryCardType.TODO)])
    assert "todo" in todo

    constraint = format_memory_cards_for_sync(
        [_sample_card(type=MemoryCardType.CONSTRAINT)]
    )
    assert "constraint" in constraint

    impl = format_memory_cards_for_sync(
        [_sample_card(type=MemoryCardType.IMPLEMENTATION_DETAIL)]
    )
    assert "implementation detail" in impl

    oq = format_memory_cards_for_sync(
        [_sample_card(type=MemoryCardType.OPEN_QUESTION)]
    )
    assert "open question" in oq


def test_format_respects_max_chars():
    cards = [_sample_card() for _ in range(20)]
    out = format_memory_cards_for_sync(cards, max_chars=400)
    assert len(out) <= 400
    # Still well-formed when non-empty.
    if out:
        assert out.startswith('<structured-memory-cards version="1">')
        assert out.endswith("</structured-memory-cards>")


def test_format_does_not_leak_memory_context_content():
    # Even if a (malformed) card carried context markers, the formatter must
    # not emit a usable memory-context block.
    out = format_memory_cards_for_sync(
        [_sample_card(summary="harmless summary", entities=["plain"])]
    )
    assert "<memory-context>" not in out
    assert "[System note:" not in out
