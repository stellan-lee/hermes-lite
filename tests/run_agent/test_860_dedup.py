"""Tests for issue #860 — SQLite session transcript deduplication.

Verifies that:
1. _flush_messages_to_session_db uses _last_flushed_db_idx to avoid re-writing
2. Multiple _persist_session calls don't duplicate messages
3. append_to_transcript(skip_db=True) skips SQLite but writes JSONL
4. The gateway doesn't double-write messages the agent already persisted
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch



# ---------------------------------------------------------------------------
# Test: _flush_messages_to_session_db only writes new messages
# ---------------------------------------------------------------------------

class TestFlushDeduplication:
    """Verify _flush_messages_to_session_db tracks what it already wrote."""

    def _make_agent(self, session_db):
        """Create a minimal AIAgent with a real session DB."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            from run_agent import AIAgent
            agent = AIAgent(
                api_key="test-key",
                base_url="https://openrouter.ai/api/v1",
                model="test/model",
                quiet_mode=True,
                session_db=session_db,
                session_id="test-session-860",
                skip_context_files=True,
                skip_memory=True,
            )
        # Simulate lazy session creation (normally done by run_conversation)
        agent._ensure_db_session()
        return agent

    def test_flush_writes_only_new_messages(self):
        """First flush writes all new messages, second flush writes none."""
        from marlow_state import SessionDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = SessionDB(db_path=db_path)

            agent = self._make_agent(db)

            conversation_history = [
                {"role": "user", "content": "old message"},
            ]
            messages = list(conversation_history) + [
                {"role": "user", "content": "new question"},
                {"role": "assistant", "content": "new answer"},
            ]

            # First flush — should write 2 new messages
            agent._flush_messages_to_session_db(messages, conversation_history)

            rows = db.get_messages(agent.session_id)
            assert len(rows) == 2, f"Expected 2 messages, got {len(rows)}"

            # Second flush with SAME messages — should write 0 new messages
            agent._flush_messages_to_session_db(messages, conversation_history)

            rows = db.get_messages(agent.session_id)
            assert len(rows) == 2, f"Expected still 2 messages after second flush, got {len(rows)}"

    def test_flush_writes_incrementally(self):
        """Messages added between flushes are written exactly once."""
        from marlow_state import SessionDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = SessionDB(db_path=db_path)

            agent = self._make_agent(db)

            conversation_history = []
            messages = [
                {"role": "user", "content": "hello"},
            ]

            # First flush — 1 message
            agent._flush_messages_to_session_db(messages, conversation_history)
            rows = db.get_messages(agent.session_id)
            assert len(rows) == 1

            # Add more messages
            messages.append({"role": "assistant", "content": "hi there"})
            messages.append({"role": "user", "content": "follow up"})

            # Second flush — should write only 2 new messages
            agent._flush_messages_to_session_db(messages, conversation_history)
            rows = db.get_messages(agent.session_id)
            assert len(rows) == 3, f"Expected 3 total messages, got {len(rows)}"

    def test_persist_session_multiple_calls_no_duplication(self):
        """Multiple _persist_session calls don't duplicate DB entries."""
        from marlow_state import SessionDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = SessionDB(db_path=db_path)

            agent = self._make_agent(db)

            conversation_history = [{"role": "user", "content": "old"}]
            messages = list(conversation_history) + [
                {"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "q2"},
                {"role": "assistant", "content": "a2"},
            ]

            # Simulate multiple persist calls (like the agent's many exit paths)
            for _ in range(5):
                agent._persist_session(messages, conversation_history)

            rows = db.get_messages(agent.session_id)
            assert len(rows) == 4, f"Expected 4 messages, got {len(rows)} (duplication bug!)"

    def test_flush_reset_after_compression(self):
        """After compression creates a new session, flush index resets."""
        from marlow_state import SessionDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = SessionDB(db_path=db_path)

            agent = self._make_agent(db)

            # Write some messages
            messages = [
                {"role": "user", "content": "msg1"},
                {"role": "assistant", "content": "reply1"},
            ]
            agent._flush_messages_to_session_db(messages, [])

            old_session = agent.session_id
            assert agent._last_flushed_db_idx == 2

            # Simulate what _compress_context does: new session, reset idx
            agent.session_id = "compressed-session-new"
            db.create_session(session_id=agent.session_id, source="test")
            agent._last_flushed_db_idx = 0

            # Now flush compressed messages to new session
            compressed_messages = [
                {"role": "user", "content": "summary of conversation"},
            ]
            agent._flush_messages_to_session_db(compressed_messages, [])

            new_rows = db.get_messages(agent.session_id)
            assert len(new_rows) == 1

            # Old session should still have its 2 messages
            old_rows = db.get_messages(old_session)
            assert len(old_rows) == 2

    def test_legacy_compression_preserves_parent_without_loaded_history_duplicates(self):
        """Only messages beyond the durable-prefix cursor reach the old parent."""
        from marlow_state import SessionDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db = SessionDB(db_path=Path(tmpdir) / "test.db")
            agent = self._make_agent(db)
            loaded = [
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": "old answer"},
            ]
            agent._flush_messages_to_session_db(loaded, [])
            parent = agent.session_id

            compressor = MagicMock()
            compressor.compress.return_value = [
                {"role": "user", "content": "[summary]"}
            ]
            compressor._last_summary_error = None
            compressor._last_compress_aborted = False
            compressor._last_aux_model_failure_model = None
            compressor._last_aux_model_failure_error = None
            compressor.compression_count = 1
            agent.context_compressor = compressor
            agent.compression_in_place = False

            with patch.object(agent, "_build_system_prompt", return_value="sys"):
                compressed, _ = agent._compress_context(loaded, "sys")

            assert db.message_count(parent) == len(loaded)
            agent._flush_messages_to_session_db(compressed)
            assert [
                row["content"] for row in db.get_messages(agent.session_id)
            ] == ["[summary]"]

    def test_in_place_compaction_then_normal_flush_does_not_duplicate(self):
        """Compacted rows are already durable when the eventual flush runs."""
        from marlow_state import SessionDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db = SessionDB(db_path=Path(tmpdir) / "test.db")
            agent = self._make_agent(db)
            original = [
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": "old answer"},
            ]
            agent._flush_messages_to_session_db(original, [])

            compacted = [{"role": "user", "content": "[summary]"}]
            compressor = MagicMock()
            compressor.compress.return_value = compacted
            compressor.compression_count = 1
            compressor.last_prompt_tokens = 0
            compressor.last_completion_tokens = 0
            compressor._last_summary_error = None
            compressor._last_compress_aborted = False
            compressor._last_aux_model_failure_model = None
            compressor._last_aux_model_failure_error = None
            agent.context_compressor = compressor
            agent.compression_in_place = True
            with patch.object(agent, "_build_system_prompt", return_value="sys"):
                compacted_result, _ = agent._compress_context(
                    original, "sys", approx_tokens=100
                )
            assert agent._last_flushed_db_idx == len(compacted_result)

            final_messages = compacted_result + [
                {"role": "assistant", "content": "continued answer"}
            ]
            agent._flush_messages_to_session_db(final_messages)

            active = db.get_messages(agent.session_id)
            assert [row["content"] for row in active] == [
                "[summary]",
                "continued answer",
            ]
            archived = db.get_messages(agent.session_id, include_inactive=True)
            assert len(archived) == 4

    def test_in_place_persistence_failure_rolls_back_compression_state(self):
        """A failed archive transaction must leave memory and cursors unchanged."""
        from marlow_state import SessionDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db = SessionDB(db_path=Path(tmpdir) / "test.db")
            agent = self._make_agent(db)
            original = [
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": "old answer"},
            ]
            agent._flush_messages_to_session_db(original, [])
            original_cursor = agent._last_flushed_db_idx
            agent._cached_system_prompt = "original system prompt"

            compressor = MagicMock()
            compressor.compress.return_value = [
                {"role": "user", "content": "compressed summary"}
            ]
            compressor.compression_count = 7
            compressor.last_prompt_tokens = 123
            compressor.last_completion_tokens = 9
            compressor.last_total_tokens = 132
            compressor.last_compression_rough_tokens = 88
            compressor.awaiting_real_usage_after_compression = False
            compressor._ineffective_compression_count = 1
            compressor._last_compression_savings_pct = 25.0
            compressor._last_summary_error = None
            compressor._last_compress_aborted = False
            compressor._last_aux_model_failure_model = None
            compressor._last_aux_model_failure_error = None
            agent.context_compressor = compressor
            agent.compression_in_place = True

            with patch.object(
                db, "archive_and_compact", side_effect=OSError("disk full")
            ):
                result, system_prompt = agent._compress_context(
                    original, "original system prompt", approx_tokens=100
                )

            assert result is original
            assert system_prompt == "original system prompt"
            assert agent._cached_system_prompt == "original system prompt"
            assert agent._last_flushed_db_idx == original_cursor
            assert agent._last_compaction_in_place is False
            assert compressor.compression_count == 7
            assert compressor.last_prompt_tokens == 123
            assert compressor.awaiting_real_usage_after_compression is False
            assert [row["content"] for row in db.get_messages(agent.session_id)] == [
                "old question",
                "old answer",
            ]
            assert db.get_compression_lock_holder(agent.session_id) is None


# ---------------------------------------------------------------------------
# Test: append_to_transcript skip_db parameter
# ---------------------------------------------------------------------------

class TestAppendToTranscriptSkipDb:
    """Verify skip_db=True skips the SQLite write."""

    def test_skip_db_prevents_sqlite_write(self, tmp_path):
        """With skip_db=True and a real DB, message does NOT appear in SQLite."""
        from gateway.config import GatewayConfig
        from gateway.session import SessionStore
        from marlow_state import SessionDB

        db_path = tmp_path / "test_skip.db"
        db = SessionDB(db_path=db_path)

        config = GatewayConfig()
        with patch("gateway.session.SessionStore._ensure_loaded"):
            store = SessionStore(sessions_dir=tmp_path, config=config)
        store._db = db
        store._loaded = True

        session_id = "test-skip-db-real"
        db.create_session(session_id=session_id, source="test")

        msg = {"role": "assistant", "content": "hello world"}
        store.append_to_transcript(session_id, msg, skip_db=True)

        # SQLite should NOT have the message
        rows = db.get_messages(session_id)
        assert len(rows) == 0, f"Expected 0 DB rows with skip_db=True, got {len(rows)}"

    def test_default_writes_to_sqlite(self, tmp_path):
        """Without skip_db, message appears in SQLite."""
        from gateway.config import GatewayConfig
        from gateway.session import SessionStore
        from marlow_state import SessionDB

        db_path = tmp_path / "test_both.db"
        db = SessionDB(db_path=db_path)

        config = GatewayConfig()
        with patch("gateway.session.SessionStore._ensure_loaded"):
            store = SessionStore(sessions_dir=tmp_path, config=config)
        store._db = db
        store._loaded = True

        session_id = "test-default-write"
        db.create_session(session_id=session_id, source="test")

        msg = {"role": "user", "content": "test message"}
        store.append_to_transcript(session_id, msg)

        # SQLite should have the message
        rows = db.get_messages(session_id)
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Test: _last_flushed_db_idx initialization
# ---------------------------------------------------------------------------

class TestFlushIdxInit:
    """Verify _last_flushed_db_idx is properly initialized."""

    def test_init_zero(self):
        """Agent starts with _last_flushed_db_idx = 0."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            from run_agent import AIAgent
            agent = AIAgent(
                api_key="test-key",
                base_url="https://openrouter.ai/api/v1",
                model="test/model",
                quiet_mode=True,
                skip_context_files=True,
                skip_memory=True,
            )
        assert agent._last_flushed_db_idx == 0

    def test_no_session_db_noop(self):
        """Without session_db, flush is a no-op and doesn't crash."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            from run_agent import AIAgent
            agent = AIAgent(
                api_key="test-key",
                base_url="https://openrouter.ai/api/v1",
                model="test/model",
                quiet_mode=True,
                skip_context_files=True,
                skip_memory=True,
            )
        messages = [{"role": "user", "content": "test"}]
        agent._flush_messages_to_session_db(messages, [])
        # Should not crash, idx should remain 0
        assert agent._last_flushed_db_idx == 0
