from __future__ import annotations

import pytest

from hermes_state import SessionDB


def test_session_lifecycle_uses_explicit_database_only(tmp_path, isolated_hermes_home):
    database_path = tmp_path / "state" / "sessions.db"
    with SessionDB(database_path) as database:
        session_id = database.create_session(session_id="fixed")
        assert session_id == "fixed"
        assert database.has_session(session_id)
        database.set_title(session_id, "Useful title")
        database.add_turn(session_id, "hello", "world")
        assert database.load_messages(session_id) == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        summary = database.list_sessions()[0]
        assert summary.id == session_id
        assert summary.title == "Useful title"
        assert summary.message_count == 2
        assert database.latest_session_id() == session_id
        assert database.delete_session(session_id) is True
        assert database.delete_session(session_id) is False
    assert database_path.exists()
    assert database_path.stat().st_mode & 0o777 == 0o600
    assert not isolated_hermes_home.exists()


def test_sessions_are_isolated_and_ordered(tmp_path):
    with SessionDB(tmp_path / "sessions.db") as database:
        first = database.create_session("first", "first")
        second = database.create_session("second", "second")
        database.add_turn(first, "a", "b")
        database.add_turn(second, "c", "d")
        assert database.load_messages(first)[0]["content"] == "a"
        assert {item.id for item in database.list_sessions()} == {"first", "second"}
        assert database.latest_session_id() == second
        with pytest.raises(ValueError, match="limit must be"):
            database.list_sessions(True)
