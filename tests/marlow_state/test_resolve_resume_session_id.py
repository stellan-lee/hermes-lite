"""Regression guard for #15000: --resume <id> after compression loses messages.

Legacy context compression ends the current session and forks a continuation
linked by ``parent_session_id``. The parent is preserved for archive/search,
but resume must target the latest populated compression continuation. Generic
branch and delegated-agent children use the same parent field, so they must
not capture resume routing.
"""
import time

import pytest

from marlow_state import SessionDB


@pytest.fixture
def db(tmp_path):
    return SessionDB(tmp_path / "state.db")


def _make_chain(db: SessionDB, ids_with_parent):
    """Create sessions in order, forcing started_at so ordering is deterministic."""
    base = int(time.time()) - 10_000
    for i, (sid, parent) in enumerate(ids_with_parent):
        db.create_session(sid, source="cli", parent_session_id=parent)
        db._conn.execute(
            "UPDATE sessions SET started_at = ? WHERE id = ?",
            (base + i * 100, sid),
        )
    for sid, parent in ids_with_parent:
        if parent:
            child_started = db._conn.execute(
                "SELECT started_at FROM sessions WHERE id = ?", (sid,)
            ).fetchone()[0]
            db._conn.execute(
                "UPDATE sessions SET ended_at = ?, end_reason = 'compression' "
                "WHERE id = ?",
                (child_started, parent),
            )
    db._conn.commit()


def test_redirects_from_empty_head_to_descendant_with_messages(db):
    # Reproducer shape from #15000: 6 sessions, only the 5th holds messages.
    _make_chain(db, [
        ("head",   None),
        ("mid1",   "head"),
        ("mid2",   "mid1"),
        ("mid3",   "mid2"),
        ("bulk",   "mid3"),    # has messages
        ("tail",   "bulk"),    # empty tail after another compression
    ])
    for i in range(5):
        db.append_message("bulk", role="user", content=f"msg {i}")

    assert db.resolve_resume_session_id("head") == "bulk"


def test_returns_self_when_session_has_messages(db):
    _make_chain(db, [("root", None), ("child", "root")])
    db.append_message("root", role="user", content="hi")
    db.append_message("child", role="assistant", content="summary")
    assert db.resolve_resume_session_id("root") == "child"


def test_returns_self_when_no_descendant_has_messages(db):
    _make_chain(db, [("root", None), ("child1", "root"), ("child2", "child1")])
    assert db.resolve_resume_session_id("root") == "root"


def test_returns_self_for_isolated_session(db):
    db.create_session("isolated", source="cli")
    assert db.resolve_resume_session_id("isolated") == "isolated"


def test_returns_self_for_nonexistent_session(db):
    assert db.resolve_resume_session_id("does_not_exist") == "does_not_exist"


def test_empty_session_id_passthrough(db):
    assert db.resolve_resume_session_id("") == ""
    assert db.resolve_resume_session_id(None) is None


def test_walks_from_middle_of_chain(db):
    # If the user happens to know an intermediate ID, we still find the msg-bearing descendant.
    _make_chain(db, [("a", None), ("b", "a"), ("c", "b"), ("d", "c")])
    db.append_message("d", role="user", content="x")
    assert db.resolve_resume_session_id("b") == "d"
    assert db.resolve_resume_session_id("c") == "d"


def test_ignores_unrelated_newer_child_and_uses_compression_continuation(db):
    base = time.time() - 100
    db.create_session("parent", source="cli")
    db.create_session("delegate", source="cli", parent_session_id="parent")
    db._conn.execute(
        "UPDATE sessions SET started_at = ? WHERE id = 'delegate'", (base,)
    )
    db._conn.execute(
        "UPDATE sessions SET ended_at = ?, end_reason = 'compression' "
        "WHERE id = 'parent'",
        (base + 10,),
    )
    db.create_session("continuation", source="cli", parent_session_id="parent")
    db._conn.execute(
        "UPDATE sessions SET started_at = ? WHERE id = 'continuation'", (base + 11,)
    )
    db._conn.commit()
    db.append_message("parent", role="user", content="preserved original")
    db.append_message("delegate", role="assistant", content="unrelated")
    db.append_message("continuation", role="assistant", content="summary")

    assert db.get_compression_lineage("continuation") == ["parent", "continuation"]
    assert db.resolve_resume_session_id("parent") == "continuation"


def test_explicit_marker_beats_later_unrelated_children_in_both_directions(db):
    db.create_session("parent", source="cli")
    db.append_message("parent", role="user", content="preserved original")
    db.rotate_session_for_compression(
        "parent",
        "continuation",
        source="cli",
        system_prompt="compressed prompt",
    )
    db.append_message("continuation", role="assistant", content="summary")

    # These are created later and share the generic parent edge, but neither
    # is a compression continuation.
    db.create_session("later-branch", source="cli", parent_session_id="parent")
    db.create_session("later-delegate", source="cli", parent_session_id="parent")
    db._conn.execute(
        "UPDATE sessions SET started_at = started_at + 1000 "
        "WHERE id IN ('later-branch', 'later-delegate')"
    )
    db._conn.commit()

    continuation = db.get_session("continuation")
    assert continuation["continuation_type"] == "compression"
    assert db.get_compression_tip("parent") == "continuation"
    assert db.get_compression_lineage("continuation") == ["parent", "continuation"]
    assert db.get_compression_lineage("later-branch") == ["later-branch"]
    assert db.resolve_resume_session_id("parent") == "continuation"


def test_legacy_fallback_keeps_earliest_child_when_later_delegate_exists(db):
    base = time.time() - 100
    db.create_session("legacy-parent", source="cli")
    db._conn.execute(
        "UPDATE sessions SET ended_at = ?, end_reason = 'compression' WHERE id = ?",
        (base, "legacy-parent"),
    )
    db.create_session(
        "legacy-continuation", source="cli", parent_session_id="legacy-parent"
    )
    db.create_session(
        "later-delegate", source="cli", parent_session_id="legacy-parent"
    )
    db._conn.execute(
        "UPDATE sessions SET started_at = ? WHERE id = ?",
        (base + 1, "legacy-continuation"),
    )
    db._conn.execute(
        "UPDATE sessions SET started_at = ? WHERE id = ?",
        (base + 20, "later-delegate"),
    )
    db._conn.commit()
    db.append_message("legacy-continuation", role="assistant", content="summary")
    db.append_message("later-delegate", role="assistant", content="unrelated")

    assert db.get_compression_tip("legacy-parent") == "legacy-continuation"
    assert db.get_compression_lineage("later-delegate") == ["later-delegate"]
    assert db.resolve_resume_session_id("legacy-parent") == "legacy-continuation"


def test_legacy_fallback_does_not_claim_late_unrelated_only_child(db):
    base = time.time() - 100
    db.create_session("legacy-parent", source="cli")
    db._conn.execute(
        "UPDATE sessions SET ended_at = ?, end_reason = 'compression' WHERE id = ?",
        (base, "legacy-parent"),
    )
    db.create_session(
        "late-branch", source="cli", parent_session_id="legacy-parent"
    )
    db._conn.execute(
        "UPDATE sessions SET started_at = ? WHERE id = ?",
        (base + 6, "late-branch"),
    )
    db._conn.commit()
    db.append_message("late-branch", role="assistant", content="unrelated")

    assert db.get_compression_tip("legacy-parent") == "legacy-parent"
    assert db.get_compression_lineage("late-branch") == ["late-branch"]
    assert db.resolve_resume_session_id("legacy-parent") == "legacy-parent"


def test_v15_migration_marks_only_earliest_legacy_continuation(tmp_path):
    path = tmp_path / "legacy.db"
    legacy = SessionDB(path)
    legacy.create_session("parent", source="cli")
    legacy._conn.execute(
        "UPDATE sessions SET ended_at = 100, end_reason = 'compression' "
        "WHERE id = 'parent'"
    )
    legacy.create_session("continuation", source="cli", parent_session_id="parent")
    legacy.create_session("later-delegate", source="cli", parent_session_id="parent")
    legacy._conn.execute(
        "UPDATE sessions SET started_at = 101 WHERE id = 'continuation'"
    )
    legacy._conn.execute(
        "UPDATE sessions SET started_at = 120 WHERE id = 'later-delegate'"
    )
    legacy._conn.execute("UPDATE schema_version SET version = 14")
    legacy._conn.commit()
    legacy.close()

    migrated = SessionDB(path)
    assert migrated.get_session("continuation")["continuation_type"] == "compression"
    assert migrated.get_session("later-delegate")["continuation_type"] is None
    assert migrated.get_compression_tip("parent") == "continuation"
