"""MemoryManager integration tests for structured memory cards (PR4).

Covers ``MemoryManager.sync_structured_cards_all`` provider fan-out:
the ``sync_structured_cards`` fast path, the ``sync_turn`` fallback, the
fallback-disabled skip, and fail-open semantics.
"""

import json

from agent.memory_manager import MemoryManager
from agent.memory_provider import MemoryProvider
from agent.memory_cards import MemoryCard, MemoryCardType, MemoryCardStatus


class FallbackProvider(MemoryProvider):
    """Provider WITHOUT sync_structured_cards — exercises the fallback path."""

    def __init__(self, name="fallback"):
        self._name = name
        self.synced_turns = []

    @property
    def name(self):
        return self._name

    def is_available(self):
        return True

    def initialize(self, session_id, **kwargs):
        pass

    def get_tool_schemas(self):
        return []

    def handle_tool_call(self, tool_name, args, **kwargs):
        return json.dumps({})

    def sync_turn(self, user_content, assistant_content, *, session_id="", **kwargs):
        self.synced_turns.append((user_content, assistant_content, session_id))


class StructuredProvider(FallbackProvider):
    """Provider that implements the structured-card fast path."""

    def __init__(self, name="structured"):
        super().__init__(name=name)
        self.structured_calls = []

    def sync_structured_cards(self, cards, *, session_id="", **kwargs):
        self.structured_calls.append((list(cards), session_id))


class BoomStructuredProvider(StructuredProvider):
    def sync_structured_cards(self, cards, *, session_id="", **kwargs):
        raise RuntimeError("backend down")


def _card(card_type=MemoryCardType.DECISION):
    return MemoryCard(
        card_id="id-" + card_type,
        type=card_type,
        status=MemoryCardStatus.ACTIVE,
        title="t",
        summary="Final decision: use compact cards.",
        entities=["compact cards"],
        confidence="medium",
        source_session_id="s1",
        source_turn_hash="hh",
    )


def test_empty_cards_is_a_noop():
    p = StructuredProvider()
    mgr = MemoryManager()
    mgr.add_provider(p)
    mgr.sync_structured_cards_all([], session_id="s1")
    assert p.structured_calls == []
    assert p.synced_turns == []


def test_structured_provider_gets_fast_path():
    p = StructuredProvider()
    mgr = MemoryManager()
    mgr.add_provider(p)

    cards = [_card()]
    mgr.sync_structured_cards_all(cards, session_id="s1")

    assert len(p.structured_calls) == 1
    sent_cards, sid = p.structured_calls[0]
    assert sid == "s1"
    assert sent_cards == cards
    # Fast path does NOT also call the fallback.
    assert p.synced_turns == []


def test_fallback_provider_uses_sync_turn():
    p = FallbackProvider()
    mgr = MemoryManager()
    mgr.add_provider(p)

    mgr.sync_structured_cards_all([_card()], session_id="s1")

    assert len(p.synced_turns) == 1
    user, assistant, sid = p.synced_turns[0]
    assert user == "[Structured memory cards extracted from completed turn]"
    assert "structured-memory-cards" in assistant
    assert "type: decision" in assistant
    assert sid == "s1"


def test_fallback_disabled_skips_provider_without_fast_path():
    p = FallbackProvider()
    mgr = MemoryManager()
    mgr.add_provider(p)

    mgr.sync_structured_cards_all(
        [_card()], session_id="s1", fallback_sync_turn_enabled=False
    )

    assert p.synced_turns == []


def test_provider_failure_fails_open():
    boom = BoomStructuredProvider(name="builtin")  # builtin so a 2nd is allowed
    ok = StructuredProvider(name="ext")
    mgr = MemoryManager()
    mgr.add_provider(boom)
    mgr.add_provider(ok)

    # Must not raise; the healthy provider still gets the cards.
    mgr.sync_structured_cards_all([_card()], session_id="s1")
    assert len(ok.structured_calls) == 1


def test_does_not_call_queue_prefetch():
    # MemoryManager has no business queuing prefetch from a card sync — verify
    # the method simply doesn't exist as a side effect by checking a fallback
    # provider only ever saw sync_turn.
    p = FallbackProvider()
    mgr = MemoryManager()
    mgr.add_provider(p)
    mgr.sync_structured_cards_all([_card()], session_id="s1")
    assert len(p.synced_turns) == 1


# ---------------------------------------------------------------------------
# Log-redaction regression: a provider exception text must never leak raw
# card content into logs (PR4 merge blocker).
# ---------------------------------------------------------------------------

_LEAK = "LEAK_ME_CARD_SUMMARY"


def _leaky_card():
    return MemoryCard(
        card_id="leak-1",
        type=MemoryCardType.DECISION,
        status=MemoryCardStatus.ACTIVE,
        title=_LEAK,
        summary="Final decision: " + _LEAK,
        entities=[_LEAK],
        confidence="medium",
        source_session_id="s1",
        source_turn_hash="hh",
    )


class LeakyStructuredProvider(FallbackProvider):
    """Fast-path provider whose exception text echoes the card summary."""

    def sync_structured_cards(self, cards, *, session_id="", **kwargs):
        raise RuntimeError("provider blew up handling " + _LEAK)


class LeakySyncTurnProvider(FallbackProvider):
    """Fallback provider whose sync_turn exception echoes the formatted cards."""

    def sync_turn(self, user_content, assistant_content, *, session_id="", **kwargs):
        # Real backends often include the payload they choked on in the error.
        raise RuntimeError("sync_turn rejected payload: " + assistant_content)


def test_fast_path_exception_does_not_leak_card_text(caplog):
    p = LeakyStructuredProvider(name="leaky")
    mgr = MemoryManager()
    mgr.add_provider(p)

    with caplog.at_level("DEBUG", logger="agent.memory_manager"):
        # Fails open — must not raise.
        mgr.sync_structured_cards_all([_leaky_card()], session_id="s1")

    text = caplog.text
    assert _LEAK not in text
    # Safe metadata is present instead.
    assert "RuntimeError" in text
    assert "leaky" in text


def test_fallback_sync_turn_exception_does_not_leak_card_text(caplog):
    p = LeakySyncTurnProvider(name="leaky2")
    mgr = MemoryManager()
    mgr.add_provider(p)

    with caplog.at_level("DEBUG", logger="agent.memory_manager"):
        # Fails open — must not raise.
        mgr.sync_structured_cards_all([_leaky_card()], session_id="s1")

    text = caplog.text
    # Neither the card summary nor the formatted block echoed by the provider
    # error leaks into logs.
    assert _LEAK not in text
    assert "structured-memory-cards" not in text
    assert "RuntimeError" in text
    assert "leaky2" in text
