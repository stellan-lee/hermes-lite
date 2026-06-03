from agent.memory_recall_query import build_recall_query_plan


def test_empty_none_and_non_string_inputs_do_not_crash():
    assert build_recall_query_plan("").recall_query == ""
    assert build_recall_query_plan(None).recall_query == ""
    assert build_recall_query_plan({"content": "hello"}).recall_query == ""


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
