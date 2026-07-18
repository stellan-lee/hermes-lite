"""Tests for deterministic structured-card conflict resolution (PR5)."""

from agent.memory_cards import (
    MemoryCard,
    MemoryCardStatus,
    MemoryCardType,
    format_memory_cards_for_sync,
)
from agent.memory_card_conflicts import (
    build_candidate_query,
    resolve_card_conflicts,
)


def _card(card_id, ctype, summary, entities, *, status="active", title=None):
    return MemoryCard(
        card_id=card_id,
        type=ctype,
        status=status,
        title=title or (entities[0] if entities else "t"),
        summary=summary,
        entities=list(entities),
        confidence="high",
        source_session_id="s1",
    )


def _candidate_text(card):
    return format_memory_cards_for_sync([card])


def test_explicit_english_decision_override_supersedes_prior():
    old = _card("OLD1", MemoryCardType.DECISION, "Use two-row buttons.",
                ["Telegram approval cards"])
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch to one-row buttons instead.", ["Telegram approval cards"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 1
    assert "OLD1" in new.supersedes
    assert new.conflict_group_id
    assert res.marker_count == 1
    assert res.superseded_marker_cards[0].status == MemoryCardStatus.SUPERSEDED


def test_explicit_chinese_override_supersedes_prior_decision():
    old = _card("OLD1", MemoryCardType.DECISION, "就用双行按钮。", ["审批卡片"])
    new = _card("NEW1", MemoryCardType.DECISION, "改成单行按钮。", ["审批卡片"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 1
    assert "OLD1" in new.supersedes


def test_same_topic_without_override_does_not_supersede():
    old = _card("OLD1", MemoryCardType.DECISION, "Use two-row buttons.",
                ["Telegram approval cards"])
    # New card adds detail, no override language.
    new = _card("NEW1", MemoryCardType.DECISION,
                "The two-row buttons look nice on desktop.",
                ["Telegram approval cards"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 0
    assert new.supersedes == []
    assert res.marker_count == 0


def test_without_override_supersedes_when_not_required():
    old = _card("OLD1", MemoryCardType.DECISION, "Use two-row buttons.",
                ["Telegram approval cards"])
    new = _card("NEW1", MemoryCardType.DECISION, "The layout is two-row.",
                ["Telegram approval cards"])
    res = resolve_card_conflicts(
        [new], [_candidate_text(old)], require_explicit_override=False
    )
    assert res.superseded_count == 1


def test_different_topic_does_not_supersede():
    old = _card("OLD1", MemoryCardType.DECISION, "Use two-row buttons.",
                ["Telegram approval cards"])
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch to dark mode instead.", ["Dashboard theme"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 0


def test_different_type_does_not_supersede():
    old = _card("OLD1", MemoryCardType.PREFERENCE, "Prefers two-row.",
                ["Telegram approval cards"])
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch to one-row instead.", ["Telegram approval cards"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 0


def test_open_question_resolved_by_decision_when_explicit():
    old = _card("OLD1", MemoryCardType.OPEN_QUESTION,
                "Unclear whether one-row or two-row.",
                ["Telegram approval cards"], status="open")
    new = _card("NEW1", MemoryCardType.DECISION,
                "Decided: use one-row buttons.", ["Telegram approval cards"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 1
    assert "OLD1" in new.supersedes


def test_already_superseded_candidate_ignored():
    old = _card("OLD1", MemoryCardType.DECISION, "Use two-row.",
                ["Telegram approval cards"], status=MemoryCardStatus.SUPERSEDED)
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch to one-row instead.", ["Telegram approval cards"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 0


def test_malformed_candidate_ignored():
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch to one-row instead.", ["Telegram approval cards"])
    res = resolve_card_conflicts([new], ["not a card at all; random text"])
    assert res.superseded_count == 0
    assert res.candidates_parsed == 0


def test_idless_candidate_ignored():
    # A card without a card_id (e.g. legacy PR4 text) can't be referenced.
    old = _card("", MemoryCardType.DECISION, "Use two-row.",
                ["Telegram approval cards"])
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch to one-row instead.", ["Telegram approval cards"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 0


def test_marker_card_has_status_superseded_and_no_old_raw_summary():
    old = _card("OLD1", MemoryCardType.DECISION,
                "SENSITIVE_OLD_SUMMARY two-row.", ["Telegram approval cards"])
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch to one-row instead.", ["Telegram approval cards"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    marker = res.superseded_marker_cards[0]
    assert marker.status == MemoryCardStatus.SUPERSEDED
    assert marker.superseded_by == "NEW1"
    assert "SENSITIVE_OLD_SUMMARY" not in marker.summary
    assert marker.summary == "This prior card was superseded by NEW1."


def test_deterministic_ids_and_order():
    old1 = _card("OLD1", MemoryCardType.DECISION, "Use A.", ["Topic One"])
    old2 = _card("OLD2", MemoryCardType.PREFERENCE, "Prefer X.", ["Topic Two"])
    new1 = _card("NEW1", MemoryCardType.DECISION,
                 "Switch to B instead.", ["Topic One"])
    new2 = _card("NEW2", MemoryCardType.PREFERENCE,
                 "Change to Y instead.", ["Topic Two"])
    cands = [_candidate_text(old1), _candidate_text(old2)]

    r1 = resolve_card_conflicts(
        [_card("NEW1", MemoryCardType.DECISION, "Switch to B instead.", ["Topic One"]),
         _card("NEW2", MemoryCardType.PREFERENCE, "Change to Y instead.", ["Topic Two"])],
        cands,
    )
    r2 = resolve_card_conflicts([new1, new2], cands)
    assert [m.card_id for m in r1.superseded_marker_cards] == [
        m.card_id for m in r2.superseded_marker_cards
    ]
    assert r1.marker_count == 2


def test_max_candidates_caps_processing():
    olds = [
        _card(f"OLD{i}", MemoryCardType.DECISION, "Use two-row.",
              [f"Topic {i}"])
        for i in range(10)
    ]
    texts = [_candidate_text(o) for o in olds]
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch to one-row instead.", ["Topic 0"])
    res = resolve_card_conflicts([new], texts, max_candidates=3)
    assert res.candidates_parsed == 3


def test_empty_inputs_safe():
    assert resolve_card_conflicts([], []).superseded_count == 0
    new = _card("NEW1", MemoryCardType.DECISION, "x instead", ["t"])
    assert resolve_card_conflicts([new], []).superseded_count == 0


def test_title_token_fallback_supersedes_when_no_entities():
    # Both cards lack entities → title-token overlap (stopword-filtered) is the
    # last-resort topic signal.
    old = _card("OLD1", MemoryCardType.DECISION, "Use polling.", [],
                title="Rate limiter policy")
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch to token bucket instead.", [],
                title="Rate limiter policy")
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 1


def test_stopword_only_title_overlap_does_not_supersede():
    # Unrelated decisions, no entities; shared title tokens are all stopwords/
    # scaffolding ("the", "decision", "use") → must NOT supersede.
    old = _card("OLD1", MemoryCardType.DECISION, "Use REST.", [],
                title="The API decision")
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch the theme to dark instead.", [],
                title="The theme decision")
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 0


def test_title_tokens_do_not_hijack_entity_bearing_cards():
    # Different entities but overlapping title tokens must NOT supersede
    # (entity sets disagree, so title-token fallback is disabled).
    old = _card("OLD1", MemoryCardType.DECISION, "Use two-row.",
                ["Telegram approval cards"], title="Button layout decision")
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch to dark instead.", ["Dashboard theme"],
                title="Button layout decision")
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 0


def test_build_candidate_query_is_search_friendly_and_bounded():
    card = _card("NEW1", MemoryCardType.DECISION,
                 "Switch to one-row instead.", ["Telegram approval cards"])
    q = build_candidate_query(card)
    assert "type: decision" in q
    assert "status: active" in q
    assert "structured-memory-cards" in q
    assert len(q) <= 240


# ---------------------------------------------------------------------------
# PR5 fixup 1: generic entity overlap must not supersede by itself
# ---------------------------------------------------------------------------


def test_generic_entity_only_overlap_does_not_supersede():
    # Both cards mention only the generic entity "API" — not the same topic.
    old = _card("OLD1", MemoryCardType.DECISION, "Use REST for the service.",
                ["API"])
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch to GraphQL instead for the service.", ["API"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 0


def test_specific_entity_overlap_still_supersedes():
    old = _card("OLD1", MemoryCardType.DECISION, "Use two rows.",
                ["Telegram approval cards", "API"])
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch to one row instead.", ["Telegram approval cards", "API"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 1
    assert "OLD1" in new.supersedes


def test_code_identifier_entity_overlap_still_supersedes():
    old = _card("OLD1", MemoryCardType.DECISION, "Use sync prefetch.",
                ["queue_prefetch_all"])
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch to async instead.", ["queue_prefetch_all"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 1


def test_different_topic_with_shared_generic_entity_does_not_supersede():
    old = _card("OLD1", MemoryCardType.DECISION, "Use Postgres.",
                ["Database backend", "DB"])
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch to dark theme instead.", ["Dashboard theme", "DB"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 0


# ---------------------------------------------------------------------------
# PR5 fixup 2: tighten open_question -> decision resolution
# ---------------------------------------------------------------------------


def test_open_question_not_resolved_by_bare_use():
    old = _card("OLD1", MemoryCardType.OPEN_QUESTION,
                "Unclear which layout.", ["Telegram approval cards"], status="open")
    # Plain decision using "use" — no explicit resolved/decided language.
    new = _card("NEW1", MemoryCardType.DECISION,
                "Use one-row buttons.", ["Telegram approval cards"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 0


def test_open_question_resolved_by_explicit_resolved_signal():
    old = _card("OLD1", MemoryCardType.OPEN_QUESTION,
                "Unclear which layout.", ["Telegram approval cards"], status="open")
    new = _card("NEW1", MemoryCardType.DECISION,
                "Resolved: one-row buttons.", ["Telegram approval cards"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 1


def test_open_question_resolved_by_final_decision_signal():
    old = _card("OLD1", MemoryCardType.OPEN_QUESTION,
                "Unclear which layout.", ["Telegram approval cards"], status="open")
    new = _card("NEW1", MemoryCardType.DECISION,
                "Final decision: one-row buttons.", ["Telegram approval cards"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 1


def test_open_question_resolved_by_chinese_explicit_signal():
    old = _card("OLD1", MemoryCardType.OPEN_QUESTION, "布局未定。", ["审批卡片"],
                status="open")
    new = _card("NEW1", MemoryCardType.DECISION, "已解决：用单行。", ["审批卡片"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 1


def test_open_question_same_topic_without_resolution_not_superseded():
    old = _card("OLD1", MemoryCardType.OPEN_QUESTION,
                "Unclear which layout.", ["Telegram approval cards"], status="open")
    # New decision adds detail, no resolved/decided/override language.
    new = _card("NEW1", MemoryCardType.DECISION,
                "The one-row layout looks clean.", ["Telegram approval cards"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 0


# ---------------------------------------------------------------------------
# PR5 fixup 3: Chinese 不要 override signal
# ---------------------------------------------------------------------------


def test_chinese_buyao_override_supersedes_prior_decision():
    old = _card("OLD1", MemoryCardType.DECISION, "就用方案 A。", ["审批卡片"])
    new = _card("NEW1", MemoryCardType.DECISION, "不要 A，用 B。", ["审批卡片"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    assert res.superseded_count == 1
    assert "OLD1" in new.supersedes


# ---------------------------------------------------------------------------
# PR5 fixup 5: marker carries old card id (for marker-only recall suppression)
# ---------------------------------------------------------------------------


def test_marker_card_carries_old_card_id_in_supersedes():
    old = _card("OLD1", MemoryCardType.DECISION, "Use two rows.",
                ["Telegram approval cards"])
    new = _card("NEW1", MemoryCardType.DECISION,
                "Switch to one row instead.", ["Telegram approval cards"])
    res = resolve_card_conflicts([new], [_candidate_text(old)])
    marker = res.superseded_marker_cards[0]
    assert marker.supersedes == ["OLD1"]
    assert marker.superseded_by == "NEW1"
