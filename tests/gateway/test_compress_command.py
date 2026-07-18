"""Tests for gateway /compress user-facing messaging."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionEntry, SessionSource, build_session_key


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


def _make_event(text: str = "/compress") -> MessageEvent:
    return MessageEvent(text=text, source=_make_source(), message_id="m1")


def _make_history() -> list[dict[str, str]]:
    return [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
        {"role": "user", "content": "three"},
        {"role": "assistant", "content": "four"},
    ]


def _make_runner(history: list[dict[str, str]]):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="***")}
    )
    session_entry = SessionEntry(
        session_key=build_session_key(_make_source()),
        session_id="sess-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.TELEGRAM,
        chat_type="dm",
    )
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = session_entry
    runner.session_store.load_transcript.return_value = history
    runner.session_store.rewrite_transcript = MagicMock()
    runner.session_store.update_session = MagicMock()
    runner.session_store._save = MagicMock()
    def _publish(session_key, parent_session_id, child_session_id):
        assert session_key == session_entry.session_key
        assert session_entry.session_id == parent_session_id
        session_entry.session_id = child_session_id
        session_entry.last_prompt_tokens = 0
        return session_entry
    runner.session_store.publish_compression_continuation.side_effect = _publish
    runner._session_db = MagicMock(name="durable_session_db")
    return runner


@pytest.mark.asyncio
async def test_compress_command_reports_noop_without_success_banner():
    history = _make_history()
    runner = _make_runner(history)
    agent_instance = MagicMock()
    agent_instance.shutdown_memory_provider = MagicMock()
    agent_instance.close = MagicMock()
    agent_instance._cached_system_prompt = ""
    agent_instance.tools = None
    agent_instance.context_compressor.has_content_to_compress.return_value = True
    agent_instance.session_id = "sess-1"
    agent_instance._compress_context.return_value = (list(history), "")

    def _estimate(messages, **_kwargs):
        assert messages == history
        return 100

    with (
        patch("gateway.run._resolve_runtime_agent_kwargs", return_value={"api_key": "test-key"}),
        patch("gateway.run._resolve_gateway_model", return_value="test-model"),
        patch("run_agent.AIAgent", return_value=agent_instance),
        patch("agent.model_metadata.estimate_request_tokens_rough", side_effect=_estimate),
    ):
        result = await runner._handle_compress_command(_make_event())

    assert "No changes from compression" in result
    assert "Compressed:" not in result
    assert "Approx request size: ~100 tokens (unchanged)" in result
    agent_instance.shutdown_memory_provider.assert_called_once()
    agent_instance.close.assert_called_once()


@pytest.mark.asyncio
async def test_compress_command_explains_when_token_estimate_rises():
    history = _make_history()
    compressed = [
        history[0],
        {"role": "assistant", "content": "Dense summary that still counts as more tokens."},
        history[-1],
    ]
    runner = _make_runner(history)
    agent_instance = MagicMock()
    agent_instance.shutdown_memory_provider = MagicMock()
    agent_instance.close = MagicMock()
    agent_instance._cached_system_prompt = ""
    agent_instance.tools = None
    agent_instance.context_compressor.has_content_to_compress.return_value = True
    agent_instance.session_id = "sess-1"
    agent_instance._compress_context.return_value = (compressed, "")

    def _estimate(messages, **_kwargs):
        if messages == history:
            return 100
        if messages == compressed:
            return 120
        raise AssertionError(f"unexpected transcript: {messages!r}")

    with (
        patch("gateway.run._resolve_runtime_agent_kwargs", return_value={"api_key": "test-key"}),
        patch("gateway.run._resolve_gateway_model", return_value="test-model"),
        patch("run_agent.AIAgent", return_value=agent_instance),
        patch("agent.model_metadata.estimate_request_tokens_rough", side_effect=_estimate),
    ):
        result = await runner._handle_compress_command(_make_event())

    assert "Compressed: 4 → 3 messages" in result
    assert "Approx request size: ~100 → ~120 tokens" in result
    assert "denser summaries" in result
    agent_instance.shutdown_memory_provider.assert_called_once()
    agent_instance.close.assert_called_once()


@pytest.mark.asyncio
async def test_in_place_compress_keeps_archived_rows(tmp_path):
    """Gateway must not hard-rewrite after the agent soft-archives in place."""
    from hermes_state import SessionDB

    history = _make_history()
    compressed = [{"role": "user", "content": "durable summary"}]
    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session(session_id="sess-1", source="telegram")
    for message in history:
        db.append_message("sess-1", message["role"], message["content"])

    runner = _make_runner(history)
    runner.session_store.rewrite_transcript.side_effect = db.replace_messages
    agent_instance = MagicMock()
    agent_instance.shutdown_memory_provider = MagicMock()
    agent_instance.close = MagicMock()
    agent_instance._cached_system_prompt = ""
    agent_instance.tools = None
    agent_instance.session_id = "sess-1"
    agent_instance._last_compaction_in_place = True
    agent_instance.context_compressor.has_content_to_compress.return_value = True
    agent_instance.context_compressor._last_compress_aborted = False
    agent_instance.context_compressor._last_summary_error = None
    agent_instance.context_compressor._last_aux_model_failure_model = None
    agent_instance.context_compressor._last_aux_model_failure_error = None

    def compact(*_args, **_kwargs):
        db.archive_and_compact("sess-1", compressed)
        return compressed, ""

    agent_instance._compress_context.side_effect = compact

    with (
        patch("gateway.run._resolve_runtime_agent_kwargs", return_value={"api_key": "test-key"}),
        patch("gateway.run._resolve_gateway_model", return_value="test-model"),
        patch("run_agent.AIAgent", return_value=agent_instance),
        patch("agent.model_metadata.estimate_request_tokens_rough", return_value=50),
    ):
        await runner._handle_compress_command(_make_event())

    runner.session_store.rewrite_transcript.assert_not_called()
    assert [row["content"] for row in db.get_messages("sess-1")] == [
        "durable summary"
    ]
    all_rows = db.get_messages("sess-1", include_inactive=True)
    assert len(all_rows) == len(history) + len(compressed)
    assert sum(not row["active"] for row in all_rows) == len(history)


@pytest.mark.asyncio
async def test_partial_compress_forces_rotation_before_tail_rejoin():
    history = _make_history()
    runner = _make_runner(history)
    agent_instance = MagicMock()
    agent_instance.shutdown_memory_provider = MagicMock()
    agent_instance.close = MagicMock()
    agent_instance._cached_system_prompt = ""
    agent_instance.tools = None
    agent_instance.session_id = "sess-1"
    agent_instance.compression_in_place = True
    agent_instance.context_compressor.has_content_to_compress.return_value = True
    agent_instance.context_compressor._last_compress_aborted = False
    agent_instance.context_compressor._last_summary_error = None
    agent_instance.context_compressor._last_aux_model_failure_model = None

    def compact(head, *_args, **_kwargs):
        assert agent_instance.compression_in_place is False
        assert head == history[:2]
        assert agent_instance._last_flushed_db_idx == len(head)
        agent_instance.session_id = "sess-2"
        return [{"role": "assistant", "content": "head summary"}], ""

    agent_instance._compress_context.side_effect = compact

    with (
        patch("gateway.run._resolve_runtime_agent_kwargs", return_value={"api_key": "test-key"}),
        patch("gateway.run._resolve_gateway_model", return_value="test-model"),
        patch("run_agent.AIAgent", return_value=agent_instance) as agent_ctor,
        patch("agent.model_metadata.estimate_request_tokens_rough", return_value=50),
    ):
        await runner._handle_compress_command(_make_event("/compress here 1"))

    assert agent_ctor.call_args.kwargs["session_db"] is runner._session_db
    runner.session_store.rewrite_transcript.assert_called_once()
    persisted = runner.session_store.rewrite_transcript.call_args.args[1]
    assert persisted[-2:] == history[-2:]


@pytest.mark.parametrize("command", ["/compress", "/compress here 1"])
@pytest.mark.parametrize("failure_stage", ["sqlite", "route_file"])
@pytest.mark.asyncio
async def test_rotating_compress_keeps_parent_route_until_every_write_succeeds(
    command, failure_stage
):
    history = _make_history()
    runner = _make_runner(history)
    session_entry = runner.session_store.get_or_create_session.return_value
    session_entry.last_prompt_tokens = 77
    agent_instance = MagicMock()
    agent_instance.shutdown_memory_provider = MagicMock()
    agent_instance.close = MagicMock()
    agent_instance._cached_system_prompt = ""
    agent_instance.tools = None
    agent_instance.session_id = "sess-1"
    agent_instance.compression_in_place = False
    agent_instance.context_compressor.has_content_to_compress.return_value = True
    agent_instance.context_compressor._last_compress_aborted = False
    agent_instance.context_compressor._last_summary_error = None
    agent_instance.context_compressor._last_aux_model_failure_model = None

    def compact(head, *_args, **_kwargs):
        agent_instance.session_id = "sess-2"
        return [{"role": "assistant", "content": f"summary of {len(head)}"}], ""

    agent_instance._compress_context.side_effect = compact
    if failure_stage == "sqlite":
        runner.session_store.rewrite_transcript.side_effect = OSError(
            "simulated SQLite write failure"
        )
    else:
        runner.session_store.publish_compression_continuation.side_effect = OSError(
            "simulated sessions.json fsync failure"
        )

    with (
        patch("gateway.run._resolve_runtime_agent_kwargs", return_value={"api_key": "test-key"}),
        patch("gateway.run._resolve_gateway_model", return_value="test-model"),
        patch("run_agent.AIAgent", return_value=agent_instance),
        patch("agent.model_metadata.estimate_request_tokens_rough", return_value=50),
    ):
        result = await runner._handle_compress_command(_make_event(command))

    assert "Compression failed" in result
    assert session_entry.session_id == "sess-1"
    assert session_entry.last_prompt_tokens == 77
    assert agent_instance.session_id == "sess-1"
    runner._session_db.rollback_compression_rotation.assert_called_once_with(
        "sess-1", "sess-2"
    )
    runner.session_store.update_session.assert_not_called()
    if failure_stage == "sqlite":
        runner.session_store.publish_compression_continuation.assert_not_called()


@pytest.mark.asyncio
async def test_compress_command_appends_warning_when_compression_aborts():
    """When the auxiliary summariser fails and the compressor ABORTS (returns
    messages unchanged), /compress must append a visible ⚠️ warning to its
    reply telling the user nothing was dropped and how to retry. Otherwise
    the failure is silently logged and the user has no idea why nothing
    happened."""
    history = _make_history()
    # Abort path: compressor returns the input messages unchanged.
    compressed = list(history)
    runner = _make_runner(history)
    agent_instance = MagicMock()
    agent_instance.shutdown_memory_provider = MagicMock()
    agent_instance.close = MagicMock()
    agent_instance._cached_system_prompt = ""
    agent_instance.tools = None
    agent_instance.context_compressor.has_content_to_compress.return_value = True
    # Simulate compression aborting (force=True bypassed cooldown but the
    # aux LLM is genuinely broken).
    agent_instance.context_compressor._last_compress_aborted = True
    agent_instance.context_compressor._last_summary_fallback_used = False
    agent_instance.context_compressor._last_summary_dropped_count = 0
    agent_instance.context_compressor._last_summary_error = (
        "404 model not found: gemini-3-flash-preview"
    )
    agent_instance.session_id = "sess-1"
    agent_instance._compress_context.return_value = (compressed, "")

    def _estimate(messages, **_kwargs):
        if messages == history:
            return 100
        if messages == compressed:
            return 100
        raise AssertionError(f"unexpected transcript: {messages!r}")

    with (
        patch("gateway.run._resolve_runtime_agent_kwargs", return_value={"api_key": "***"}),
        patch("gateway.run._resolve_gateway_model", return_value="test-model"),
        patch("run_agent.AIAgent", return_value=agent_instance),
        patch("agent.model_metadata.estimate_request_tokens_rough", side_effect=_estimate),
    ):
        result = await runner._handle_compress_command(_make_event())

    # A clearly-marked warning must be appended.
    assert "⚠️" in result
    assert "Compression aborted" in result
    # Underlying error must surface so users can fix their config.
    assert "404 model not found" in result
    # User must be told nothing was dropped — the whole point of the
    # new behavior is no silent data loss.
    assert "No messages were dropped" in result
    agent_instance.shutdown_memory_provider.assert_called_once()
    agent_instance.close.assert_called_once()


@pytest.mark.asyncio
async def test_compress_command_surfaces_aux_model_failure_even_when_recovered():
    """When the user's configured ``auxiliary.compression.model`` errors out
    but compression recovers by retrying on the main model, /compress must
    STILL inform the user.  Silent recovery hides broken config the user
    needs to fix."""
    history = _make_history()
    # Compressed transcript — normal successful compression, no placeholder.
    compressed = [
        history[0],
        {"role": "assistant", "content": "summary via main model"},
        history[-1],
    ]
    runner = _make_runner(history)
    agent_instance = MagicMock()
    agent_instance.shutdown_memory_provider = MagicMock()
    agent_instance.close = MagicMock()
    agent_instance._cached_system_prompt = ""
    agent_instance.tools = None
    agent_instance.context_compressor.has_content_to_compress.return_value = True
    # Fallback placeholder was NOT used — recovery succeeded.
    agent_instance.context_compressor._last_compress_aborted = False
    agent_instance.context_compressor._last_summary_fallback_used = False
    agent_instance.context_compressor._last_summary_dropped_count = 0
    agent_instance.context_compressor._last_summary_error = None
    # But the configured aux model DID fail before the retry succeeded.
    agent_instance.context_compressor._last_aux_model_failure_model = (
        "gemini-3-flash-preview"
    )
    agent_instance.context_compressor._last_aux_model_failure_error = (
        "404 model not found: gemini-3-flash-preview"
    )
    agent_instance.session_id = "sess-1"
    agent_instance._compress_context.return_value = (compressed, "")

    def _estimate(messages, **_kwargs):
        if messages == history:
            return 100
        if messages == compressed:
            return 60
        raise AssertionError(f"unexpected transcript: {messages!r}")

    with (
        patch("gateway.run._resolve_runtime_agent_kwargs", return_value={"api_key": "***"}),
        patch("gateway.run._resolve_gateway_model", return_value="test-model"),
        patch("run_agent.AIAgent", return_value=agent_instance),
        patch("agent.model_metadata.estimate_request_tokens_rough", side_effect=_estimate),
    ):
        result = await runner._handle_compress_command(_make_event())

    # Compression succeeded
    assert "Compressed:" in result
    # No ⚠️ warning (that's reserved for dropped-turns case)
    assert "⚠️" not in result
    # But there IS an info note about the broken aux model
    assert "ℹ️" in result
    assert "gemini-3-flash-preview" in result
    assert "404" in result
    assert "auxiliary.compression.model" in result
    # The user's context is explicitly called out as intact
    assert "intact" in result
    agent_instance.shutdown_memory_provider.assert_called_once()
    agent_instance.close.assert_called_once()
