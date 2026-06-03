"""Regression coverage for keyed external-memory prefetch caches."""

from __future__ import annotations

import threading
import logging

from agent.memory_prefetch import (
    make_prefetch_entry,
    normalize_prefetch_query,
    prefetch_entry_matches,
    prefetch_entry_result,
    short_hash,
)
from agent.memory_provider import MemoryProvider


class _QueuedProvider(MemoryProvider):
    def __init__(self) -> None:
        self._entry = None
        self.scope = "scope-a"

    @property
    def name(self) -> str:
        return "queued"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id, **kwargs):
        pass

    def get_tool_schemas(self):
        return []

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        self._entry = make_prefetch_entry(
            "queued result",
            query,
            session_id=session_id,
            effective_scope=self.scope,
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        entry = self._entry
        self._entry = None
        if not prefetch_entry_matches(
            entry,
            query,
            session_id=session_id,
            effective_scope=self.scope,
        ):
            return ""
        return prefetch_entry_result(entry)


def test_queued_result_for_query_a_is_not_returned_for_query_b():
    provider = _QueuedProvider()
    provider.queue_prefetch("query A", session_id="sess-1")

    assert provider.prefetch("query B", session_id="sess-1") == ""


def test_same_query_same_scope_consumes_queued_result():
    provider = _QueuedProvider()
    provider.queue_prefetch("query A", session_id="sess-1")

    assert provider.prefetch("query A", session_id="sess-1") == "queued result"


def test_same_query_different_session_scope_does_not_consume_result():
    provider = _QueuedProvider()
    provider.queue_prefetch("query A", session_id="sess-1")

    assert provider.prefetch("query A", session_id="sess-2") == ""


def test_prefetch_query_normalization_handles_edge_values():
    assert normalize_prefetch_query(None) == ""
    assert normalize_prefetch_query("") == ""
    assert normalize_prefetch_query("  Hello\tWorld \n") == "hello world"
    assert normalize_prefetch_query("HELLO world") == "hello world"
    assert normalize_prefetch_query(123) == "123"
    assert normalize_prefetch_query("  café  東京  ") == "café 東京"


def test_short_hash_handles_edge_values_stably():
    assert short_hash(None) == ""
    assert short_hash("") == ""
    assert short_hash("  Hello World  ") == short_hash("  Hello World  ")
    assert short_hash(123) == short_hash("123")
    assert short_hash("café 東京") == short_hash("café 東京")


def test_mem0_prefetch_requires_query_and_scope_match(caplog):
    from plugins.memory.mem0 import Mem0MemoryProvider

    provider = Mem0MemoryProvider()
    provider._user_id = "user-1"
    provider._agent_id = "agent-1"
    provider._prefetch_thread = None
    provider._prefetch_result = make_prefetch_entry(
        "- remembered",
        "query A",
        session_id="sess-1",
        effective_scope=provider._prefetch_scope("sess-1"),
    )

    with caplog.at_level(logging.DEBUG, logger="plugins.memory.mem0"):
        assert provider.prefetch("query B", session_id="sess-1") == ""
    assert "query A" not in caplog.text
    assert "query B" not in caplog.text

    provider._prefetch_result = make_prefetch_entry(
        "- remembered",
        "query A",
        session_id="sess-1",
        effective_scope=provider._prefetch_scope("sess-1"),
    )
    assert "remembered" in provider.prefetch("query A", session_id="sess-1")

    provider._prefetch_result = make_prefetch_entry(
        "- remembered",
        "query A",
        session_id="sess-1",
        effective_scope=provider._prefetch_scope("sess-1"),
    )
    assert provider.prefetch("query A", session_id="sess-2") == ""


def test_hindsight_prefetch_requires_query_and_scope_match():
    from plugins.memory.hindsight import HindsightMemoryProvider

    provider = HindsightMemoryProvider()
    provider._bank_id = "bank-1"
    provider._user_id = "user-1"
    provider._agent_identity = "profile-1"
    provider._agent_workspace = "workspace-1"
    provider._session_id = "sess-1"
    provider._prefetch_thread = None
    provider._prefetch_result = make_prefetch_entry(
        "- remembered",
        "query A",
        session_id="sess-1",
        effective_scope=provider._prefetch_scope("sess-1"),
    )

    assert provider.prefetch("query B", session_id="sess-1") == ""

    provider._prefetch_result = make_prefetch_entry(
        "- remembered",
        "query A",
        session_id="sess-1",
        effective_scope=provider._prefetch_scope("sess-1"),
    )
    assert "remembered" in provider.prefetch("query A", session_id="sess-1")


def test_hindsight_prefetch_scope_includes_recall_method():
    from plugins.memory.hindsight import HindsightMemoryProvider

    provider = HindsightMemoryProvider()
    provider._bank_id = "bank-1"
    provider._user_id = "user-1"
    provider._agent_identity = "profile-1"
    provider._agent_workspace = "workspace-1"
    provider._session_id = "sess-1"
    provider._prefetch_thread = None
    provider._prefetch_result = make_prefetch_entry(
        "- reflected",
        "query A",
        session_id="sess-1",
        effective_scope=provider._prefetch_scope("sess-1"),
    )

    provider._prefetch_method = "reflect" if provider._prefetch_method != "reflect" else "recall"

    assert provider.prefetch("query A", session_id="sess-1") == ""


def test_hindsight_prefetch_scope_includes_tags_and_types():
    from plugins.memory.hindsight import HindsightMemoryProvider

    provider = HindsightMemoryProvider()
    provider._bank_id = "bank-1"
    provider._user_id = "user-1"
    provider._agent_identity = "profile-1"
    provider._agent_workspace = "workspace-1"
    provider._session_id = "sess-1"
    provider._prefetch_thread = None
    provider._recall_tags = ["alpha"]
    provider._recall_tags_match = "any"
    provider._recall_types = ["fact"]
    provider._prefetch_result = make_prefetch_entry(
        "- tagged",
        "query A",
        session_id="sess-1",
        effective_scope=provider._prefetch_scope("sess-1"),
    )

    provider._recall_tags = ["beta"]
    assert provider.prefetch("query A", session_id="sess-1") == ""

    provider._recall_tags = ["alpha"]
    provider._recall_tags_match = "any"
    provider._recall_types = ["fact"]
    provider._prefetch_result = make_prefetch_entry(
        "- typed",
        "query A",
        session_id="sess-1",
        effective_scope=provider._prefetch_scope("sess-1"),
    )

    provider._recall_types = ["preference"]
    assert provider.prefetch("query A", session_id="sess-1") == ""


def test_openviking_prefetch_requires_query_and_scope_match():
    from plugins.memory.openviking import OpenVikingMemoryProvider

    provider = OpenVikingMemoryProvider()
    provider._account = "acct"
    provider._user = "user"
    provider._agent = "agent"
    provider._session_id = "sess-1"
    provider._prefetch_thread = None
    provider._prefetch_result = make_prefetch_entry(
        "- remembered",
        "query A",
        session_id="sess-1",
        effective_scope=provider._prefetch_scope("sess-1"),
    )

    assert provider.prefetch("query B", session_id="sess-1") == ""

    provider._prefetch_result = make_prefetch_entry(
        "- remembered",
        "query A",
        session_id="sess-1",
        effective_scope=provider._prefetch_scope("sess-1"),
    )
    assert "remembered" in provider.prefetch("query A", session_id="sess-1")


def test_retaindb_prefetch_requires_query_and_scope_match():
    from plugins.memory.retaindb import RetainDBMemoryProvider

    class _Client:
        project = "project-1"

    provider = RetainDBMemoryProvider()
    provider._client = _Client()
    provider._user_id = "user"
    provider._agent_id = "agent"
    provider._session_id = "sess-1"
    provider._lock = threading.Lock()
    provider._context_result = make_prefetch_entry(
        "[RetainDB Context]\n- remembered",
        "query A",
        session_id="sess-1",
        effective_scope=provider._prefetch_scope("sess-1"),
    )

    assert provider.prefetch("query B", session_id="sess-1") == ""

    provider._context_result = make_prefetch_entry(
        "[RetainDB Context]\n- remembered",
        "query A",
        session_id="sess-1",
        effective_scope=provider._prefetch_scope("sess-1"),
    )
    assert "remembered" in provider.prefetch("query A", session_id="sess-1")


def test_retaindb_queue_prefetch_reads_with_effective_session_id():
    from plugins.memory.retaindb import RetainDBMemoryProvider

    class _Client:
        project = "project-1"

        def __init__(self):
            self.query_context_calls = []

        def query_context(self, user_id, session_id, query):
            self.query_context_calls.append((user_id, session_id, query))
            return {"results": [{"content": f"context for {session_id}"}]}

        def get_profile(self, user_id):
            return {"memories": []}

        def ask_user(self, user_id, query, reasoning_level="low"):
            return {}

        def get_agent_model(self, agent_id):
            return {}

    provider = RetainDBMemoryProvider()
    provider._client = _Client()
    provider._user_id = "user"
    provider._agent_id = "agent"
    provider._session_id = "old-session"

    provider.queue_prefetch("query A", session_id="new-session")
    for thread in provider._prefetch_threads:
        thread.join(timeout=2.0)

    assert provider._client.query_context_calls == [
        ("user", "new-session", "query A")
    ]

    assert provider.prefetch("query A", session_id="old-session") == ""

    provider.queue_prefetch("query A", session_id="new-session")
    for thread in provider._prefetch_threads:
        thread.join(timeout=2.0)

    assert "context for new-session" in provider.prefetch(
        "query A",
        session_id="new-session",
    )


def test_honcho_pending_dialectic_requires_query_and_scope_match():
    from plugins.memory.honcho import HonchoMemoryProvider

    provider = object.__new__(HonchoMemoryProvider)
    provider._cron_skipped = False
    provider._recall_mode = "context"
    provider._session_ready = lambda: True
    provider._injection_frequency = "always"
    provider._turn_count = 1
    provider._is_trivial_prompt = lambda _query: False
    provider._base_context_lock = threading.Lock()
    provider._base_context_cache = ""
    provider._manager = None
    provider._prefetch_lock = threading.Lock()
    provider._prefetch_thread = None
    provider._prefetch_thread_started_at = 0.0
    provider._prefetch_result_fired_at = 1
    provider._last_dialectic_turn = 1
    provider._dialectic_cadence = 1
    provider._config = None
    provider._session_key = "honcho-session"
    provider._prefetch_result = make_prefetch_entry(
        "remembered",
        "query A",
        session_id="sess-1",
        effective_scope=provider._session_key,
        fired_at=1,
    )

    assert provider.prefetch("query B", session_id="sess-1") == ""

    provider._prefetch_result_fired_at = 1
    provider._prefetch_result = make_prefetch_entry(
        "remembered",
        "query A",
        session_id="sess-1",
        effective_scope=provider._session_key,
        fired_at=1,
    )
    assert "remembered" in provider.prefetch("query A", session_id="sess-1")
