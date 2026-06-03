from agent.memory_recall_query import (
    _INTENT_RULES,
    _INTENT_SUBQUERY_SUFFIX,
    build_recall_query_plan,
)


def test_empty_none_and_non_string_inputs_do_not_crash():
    assert build_recall_query_plan("").recall_query == ""
    assert build_recall_query_plan(None).recall_query == ""
    assert build_recall_query_plan({"content": "hello"}).recall_query == ""


def test_empty_input_has_no_subqueries():
    assert build_recall_query_plan("").subqueries == []
    assert build_recall_query_plan(None).subqueries == []


def test_preserves_original_phrase_and_uses_recent_context():
    plan = build_recall_query_plan(
        "and the mobile version?",
        recent_messages=[
            {"role": "user", "content": "what did we decide about Telegram approval cards?"},
            {"role": "assistant", "content": "We decided compact inline buttons for desktop."},
        ],
    )

    assert "and the mobile version?" in plan.recall_query
    assert "Telegram approval cards" in plan.recall_query
    assert "compact inline buttons" in plan.recall_query
    assert plan.used_recent_context is True


def test_excludes_system_developer_tool_and_tool_call_messages():
    plan = build_recall_query_plan(
        "what did we decide?",
        recent_messages=[
            {"role": "system", "content": "system secret"},
            {"role": "developer", "content": "developer secret"},
            {"role": "tool", "content": "tool secret"},
            {"role": "assistant", "content": "assistant tool call secret", "tool_calls": [{"id": "1"}]},
            {"role": "user", "content": "safe user topic"},
        ],
    )

    assert "safe user topic" in plan.recall_query
    assert "system secret" not in plan.recall_query
    assert "developer secret" not in plan.recall_query
    assert "tool secret" not in plan.recall_query
    assert "assistant tool call secret" not in plan.recall_query


def test_strips_existing_memory_context_blocks():
    plan = build_recall_query_plan(
        "and that?",
        recent_messages=[
            {
                "role": "assistant",
                "content": "visible topic <memory-context>secret recalled text</memory-context>",
            }
        ],
    )

    assert "visible topic" in plan.recall_query
    assert "secret recalled text" not in plan.recall_query
    assert "memory-context" not in plan.recall_query


def test_long_recent_context_is_truncated():
    plan = build_recall_query_plan(
        "and the mobile version?",
        recent_messages=[{"role": "user", "content": "x" * 2000}],
        max_recent_chars=80,
        max_query_chars=500,
    )

    assert len(plan.recall_query) <= 500
    assert plan.used_recent_context is True
    assert plan.recall_query.count("x") < 2000


def test_decision_intent_detected_english_and_chinese():
    assert build_recall_query_plan(
        "what did we decide about telegram approval cards?"
    ).intent == "previous decision / final agreed approach"
    assert build_recall_query_plan(
        "之前 telegram approval cards 怎么定的？"
    ).intent == "previous decision / final agreed approach"


def test_implementation_intent_detected_english_and_chinese():
    assert build_recall_query_plan(
        "how should we implement it?"
    ).intent == "implementation detail / constraints"
    assert build_recall_query_plan(
        "这个怎么实现？"
    ).intent == "implementation detail / constraints"


def test_preference_and_status_intents_detected():
    assert build_recall_query_plan("what format do I prefer?").intent == "user preference"
    assert build_recall_query_plan("下一步还剩什么？").intent == "task status / open todo"


def test_entity_extraction_catches_expected_terms():
    plan = build_recall_query_plan(
        'what did we decide about Telegram approval cards and "compact mode"?',
        recent_messages=[
            {
                "role": "assistant",
                "content": "Use queue_prefetch_all in agent/conversation_loop.py.",
            }
        ],
    )

    assert "Telegram approval cards" in plan.entities
    assert "queue_prefetch_all" in plan.entities
    assert "agent/conversation_loop.py" in plan.entities
    assert "compact mode" in plan.entities


def test_unicode_input_works_and_max_query_chars_is_respected():
    plan = build_recall_query_plan(
        "那按钮顺序呢？",
        recent_messages=[{"role": "user", "content": "我们讨论了 Telegram approval cards 的移动端布局。"}],
        max_query_chars=120,
    )

    assert "那按钮顺序呢？" in plan.recall_query
    assert len(plan.recall_query) <= 120


# ---------------------------------------------------------------------------
# Multi-query subquery generation (PR3)
# ---------------------------------------------------------------------------


def test_every_intent_label_has_subquery_suffix():
    """Each detectable intent label must map to a subquery suffix (no drift)."""
    labels = {label for (label, _en, _zh) in _INTENT_RULES}
    assert labels == set(_INTENT_SUBQUERY_SUFFIX)


def test_subqueries_always_include_original_query_first():
    plan = build_recall_query_plan("how should we implement the queue_prefetch_all path?")
    assert plan.subqueries
    assert plan.subqueries[0] == plan.original_query
    assert "how should we implement the queue_prefetch_all path?" == plan.subqueries[0]


def test_subqueries_include_enriched_standalone_query():
    plan = build_recall_query_plan(
        "and the mobile version?",
        recent_messages=[
            {"role": "user", "content": "what did we decide about Telegram approval cards?"},
            {"role": "assistant", "content": "We decided compact inline buttons for desktop."},
        ],
    )
    # The PR2 enriched query is one of the subqueries.
    assert plan.recall_query in plan.subqueries
    # Both the follow-up phrasing and the prior topic are recoverable.
    assert any("mobile version" in s for s in plan.subqueries)
    assert any("Telegram approval cards" in s for s in plan.subqueries)


def test_subqueries_dedupe_plain_query_without_enrichment():
    plan = build_recall_query_plan("tell me a joke")
    assert plan.subqueries == ["tell me a joke"]


def test_subqueries_use_whitespace_normalized_original():
    # A plain lowercase prompt has no enrichment; whitespace is collapsed.
    plan = build_recall_query_plan("remind   me   later")
    assert plan.subqueries == ["remind me later"]


def test_subqueries_have_no_normalized_duplicates():
    from agent.memory_recall_query import _normalize_for_dedupe

    plan = build_recall_query_plan(
        'what did we decide about Telegram approval cards and "compact mode"?'
    )
    norms = [_normalize_for_dedupe(s) for s in plan.subqueries]
    assert len(norms) == len(set(norms))


def test_subqueries_capped_by_max_queries():
    plan = build_recall_query_plan(
        'what did we decide about Telegram approval cards and "compact mode"?',
        max_queries=2,
    )
    assert len(plan.subqueries) == 2


def test_subqueries_respect_max_length():
    plan = build_recall_query_plan(
        'what did we decide about Telegram approval cards and "compact mode"?',
        recent_messages=[{"role": "user", "content": "x" * 500}],
        max_subquery_chars=40,
    )
    assert plan.subqueries
    assert all(len(s) <= 40 for s in plan.subqueries)


def test_decision_intent_creates_decision_subquery():
    plan = build_recall_query_plan(
        'what did we decide about Telegram approval cards and "compact mode"?'
    )
    assert plan.intent == "previous decision / final agreed approach"
    assert any("previous decision final agreed approach" in s for s in plan.subqueries)


def test_implementation_intent_creates_implementation_subquery():
    plan = build_recall_query_plan(
        "how should we implement the queue_prefetch_all path?"
    )
    assert plan.intent == "implementation detail / constraints"
    assert any(
        "implementation details constraints code path" in s for s in plan.subqueries
    )


def test_context_dependent_prompt_subqueries_include_prior_topic():
    plan = build_recall_query_plan(
        "and the mobile version?",
        recent_messages=[
            {"role": "user", "content": "Let's finish Telegram approval cards."},
            {"role": "assistant", "content": "The desktop card uses approve and reject inline buttons."},
        ],
    )
    joined = "\n".join(plan.subqueries)
    assert "mobile version" in joined
    assert "Telegram approval cards" in joined


def test_subqueries_do_not_leak_memory_context_blocks():
    plan = build_recall_query_plan(
        "and that?",
        recent_messages=[
            {
                "role": "assistant",
                "content": "visible topic <memory-context>secret recalled text</memory-context>",
            }
        ],
    )
    joined = "\n".join(plan.subqueries)
    assert "secret recalled text" not in joined
    assert "memory-context" not in joined


def test_subqueries_do_not_leak_system_developer_tool_content():
    plan = build_recall_query_plan(
        "what did we decide?",
        recent_messages=[
            {"role": "system", "content": "system secret"},
            {"role": "developer", "content": "developer secret"},
            {"role": "tool", "content": "tool secret"},
            {"role": "assistant", "content": "assistant tool call secret", "tool_calls": [{"id": "1"}]},
            {"role": "user", "content": "safe user topic"},
        ],
    )
    joined = "\n".join(plan.subqueries)
    assert "system secret" not in joined
    assert "developer secret" not in joined
    assert "tool secret" not in joined
    assert "assistant tool call secret" not in joined


def test_subqueries_handle_unicode_and_chinese_prompts():
    plan = build_recall_query_plan(
        "那按钮顺序呢？",
        recent_messages=[{"role": "user", "content": "我们讨论了 Telegram approval cards 的移动端布局。"}],
        max_subquery_chars=120,
    )
    assert plan.subqueries
    assert plan.subqueries[0] == "那按钮顺序呢？"
    assert all(len(s) <= 120 for s in plan.subqueries)
