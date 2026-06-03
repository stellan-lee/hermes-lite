"""Post-turn integration tests for structured memory cards (PR4).

Exercises ``AIAgent._sync_external_memory_for_turn`` with the structured
card path on/off, asserting the core invariants: normal ``sync_all`` is
unchanged, structured-card sync is gated and fail-open, no prefetch is
queued, and the current API user message is never modified.
"""
from unittest.mock import MagicMock

import pytest


DECISION_TURN = (
    "which approval UX should we use?",
    "We decided to use compact inline approval cards. This is final.",
)


def _bare_agent(*, structured_enabled=False):
    from run_agent import AIAgent

    agent = AIAgent.__new__(AIAgent)
    agent._memory_manager = MagicMock()
    agent.session_id = "sess-card-1"
    agent._memory_post_turn_prefetch_enabled = False
    agent._memory_structured_cards_enabled = structured_enabled
    return agent


def test_disabled_does_not_extract_or_sync_cards():
    agent = _bare_agent(structured_enabled=False)
    agent._sync_external_memory_for_turn(
        original_user_message=DECISION_TURN[0],
        final_response=DECISION_TURN[1],
        interrupted=False,
    )
    agent._memory_manager.sync_all.assert_called_once()
    agent._memory_manager.sync_structured_cards_all.assert_not_called()


def test_enabled_with_signal_syncs_structured_cards():
    agent = _bare_agent(structured_enabled=True)
    agent._sync_external_memory_for_turn(
        original_user_message=DECISION_TURN[0],
        final_response=DECISION_TURN[1],
        interrupted=False,
    )
    agent._memory_manager.sync_structured_cards_all.assert_called_once()
    cards = agent._memory_manager.sync_structured_cards_all.call_args.args[0]
    assert cards  # at least one card extracted
    kwargs = agent._memory_manager.sync_structured_cards_all.call_args.kwargs
    assert kwargs["session_id"] == "sess-card-1"
    assert kwargs["fallback_sync_turn_enabled"] is True


def test_normal_sync_all_still_runs_when_enabled():
    agent = _bare_agent(structured_enabled=True)
    agent._sync_external_memory_for_turn(
        original_user_message=DECISION_TURN[0],
        final_response=DECISION_TURN[1],
        interrupted=False,
    )
    agent._memory_manager.sync_all.assert_called_once_with(
        DECISION_TURN[0], DECISION_TURN[1], session_id="sess-card-1"
    )


def test_card_sync_does_not_queue_prefetch():
    agent = _bare_agent(structured_enabled=True)
    agent._sync_external_memory_for_turn(
        original_user_message=DECISION_TURN[0],
        final_response=DECISION_TURN[1],
        interrupted=False,
    )
    agent._memory_manager.queue_prefetch_all.assert_not_called()


def test_low_signal_turn_writes_no_cards():
    agent = _bare_agent(structured_enabled=True)
    agent._sync_external_memory_for_turn(
        original_user_message="what's the weather?",
        final_response="It's sunny and 22 degrees today.",
        interrupted=False,
    )
    agent._memory_manager.sync_all.assert_called_once()
    agent._memory_manager.sync_structured_cards_all.assert_not_called()


def test_interrupted_turn_skips_card_sync():
    agent = _bare_agent(structured_enabled=True)
    agent._sync_external_memory_for_turn(
        original_user_message=DECISION_TURN[0],
        final_response=DECISION_TURN[1],
        interrupted=True,
    )
    agent._memory_manager.sync_all.assert_not_called()
    agent._memory_manager.sync_structured_cards_all.assert_not_called()


def test_extraction_failure_does_not_block_turn(monkeypatch):
    agent = _bare_agent(structured_enabled=True)

    def boom(*a, **k):
        raise RuntimeError("extractor exploded")

    monkeypatch.setattr("agent.memory_cards.extract_memory_cards", boom)

    # Must not raise; normal sync_all already happened.
    agent._sync_external_memory_for_turn(
        original_user_message=DECISION_TURN[0],
        final_response=DECISION_TURN[1],
        interrupted=False,
    )
    agent._memory_manager.sync_all.assert_called_once()
    agent._memory_manager.sync_structured_cards_all.assert_not_called()


def test_card_sync_failure_does_not_block_turn():
    agent = _bare_agent(structured_enabled=True)
    agent._memory_manager.sync_structured_cards_all.side_effect = RuntimeError(
        "provider down"
    )

    # Must not raise.
    agent._sync_external_memory_for_turn(
        original_user_message=DECISION_TURN[0],
        final_response=DECISION_TURN[1],
        interrupted=False,
    )
    agent._memory_manager.sync_all.assert_called_once()
    agent._memory_manager.sync_structured_cards_all.assert_called_once()


def test_user_message_not_modified_by_cards():
    agent = _bare_agent(structured_enabled=True)
    user = DECISION_TURN[0]
    agent._sync_external_memory_for_turn(
        original_user_message=user,
        final_response=DECISION_TURN[1],
        interrupted=False,
    )
    # sync_all received the verbatim original user message.
    assert agent._memory_manager.sync_all.call_args.args[0] == user
    assert user == "which approval UX should we use?"
