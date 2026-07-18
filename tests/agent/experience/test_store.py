from __future__ import annotations

import math
import sqlite3
import threading
from pathlib import Path

import pytest

from agent.experience.store import ExperienceStore
from marlow_state import SessionDB


REPO_ID = "repo_test"
PROJECT_ID = "project_test"


def _body(guidance: str = "Use a focused verification before the full suite.") -> dict[str, str]:
    return {
        "applies_when": "Changing SQLite-backed experience state",
        "does_not_apply_when": "The change is documentation only",
        "guidance": guidance,
        "rationale": "Focused checks keep failures attributable.",
    }


def _policy(store: ExperienceStore, *, injection_allowed: bool = True) -> None:
    store.upsert_scope_policy(
        principal_id="local-owner",
        repository_id=REPO_ID,
        project_id=PROJECT_ID,
        project_root_rel="apps/api",
        recall_allowed=True,
        injection_allowed=injection_allowed,
        max_egress_policy="explicit_any_provider",
        updated_at=1.0,
    )


def _lesson(
    store: ExperienceStore,
    *,
    item_id: str = "lesson_test",
    project_id: str = PROJECT_ID,
    status: str = "active",
    sensitivity: str = "normal",
    egress_policy: str = "same_provider_trust_domain",
    producer_trust_domain: str = "provider:a",
    tags: dict[str, list[str]] | None = None,
) -> dict:
    created = store.create_lesson(
        item_id=item_id,
        idempotency_key=f"create:{item_id}",
        principal_id="local-owner",
        scope_type="project",
        scope_id=project_id,
        repository_id=REPO_ID,
        project_id=project_id,
        title=f"Lesson {item_id}",
        summary="A bounded, manually curated lesson.",
        body=_body(),
        tags=tags or {"technology": ["sqlite"], "task_type": ["persistence"]},
        confidence=0.8,
        sensitivity=sensitivity,
        egress_policy=egress_policy,
        producer_trust_domain=producer_trust_domain,
        created_by="user",
        source_session_id="source-session",
        source_turn_id="source-turn",
        source_work_id="source-work",
        source_hash="a" * 64,
        created_at=2.0,
    )
    if status == "active":
        return store.approve_lesson(item_id, transitioned_at=3.0)
    if status != "candidate":
        return store.transition_lesson(item_id, status, transitioned_at=3.0)
    return created


def _search(store: ExperienceStore, **overrides: object) -> list[dict]:
    values: dict[str, object] = {
        "principal_id": "local-owner",
        "scope_type": "project",
        "scope_id": PROJECT_ID,
        "repository_id": REPO_ID,
        "project_id": PROJECT_ID,
        "provider_trust_domain": "provider:a",
        "provider_is_local": False,
        "tags": {"technology": ["sqlite"]},
        "limit": 10,
    }
    values.update(overrides)
    return store.search_lessons(**values)


def test_manual_lifecycle_uses_immutable_idempotent_revisions(tmp_path: Path) -> None:
    path = (tmp_path / "profile" / "state.db").resolve()
    with ExperienceStore(path) as store:
        _policy(store)
        first = _lesson(store, status="candidate")
        replay = _lesson(store, status="candidate")
        assert first["id"] == replay["id"] == "lesson_test"
        assert first["current_status"] == "candidate"
        assert first["current_revision"] == 1

        active = store.approve_lesson("lesson_test", transitioned_at=3.0)
        assert active["current_status"] == "active"
        assert store.approve_lesson("lesson_test")["current_status"] == "active"

        edited = store.edit_lesson(
            "lesson_test",
            body=_body("Checkpoint the WAL after the focused verification."),
            tags={"technology": ["sqlite", "wal"], "task_type": ["persistence"]},
            edit_reason="Clarify the verified sequence",
            idempotency_key="edit:lesson_test:2",
            edited_at=4.0,
        )
        edit_replay = store.edit_lesson(
            "lesson_test",
            body=_body("Checkpoint the WAL after the focused verification."),
            tags={"technology": ["sqlite", "wal"], "task_type": ["persistence"]},
            idempotency_key="edit:lesson_test:2",
        )
        assert edited["revision"]["revision"] == 2
        assert edit_replay["revision"]["revision"] == 2
        history = store.get_item("lesson_test", include_history=True)
        assert history is not None
        assert [revision["revision"] for revision in history["revisions"]] == [1, 2]
        assert history["revisions"][0]["body"]["guidance"] != history["revisions"][1]["body"]["guidance"]

        with sqlite3.connect(path) as raw:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                raw.execute(
                    "UPDATE experience_item_revisions SET title = 'rewrite' "
                    "WHERE item_id = 'lesson_test' AND revision = 1"
                )

        retracted = store.retract_lesson(
            "lesson_test", reason="No longer applicable", transitioned_at=5.0
        )
        assert retracted["current_status"] == "retracted"
        assert retracted["deleted_at"] == 5.0
        assert _search(store) == []
        with pytest.raises(ValueError, match="terminal"):
            store.edit_lesson("lesson_test", title="Cannot rewrite history")


def test_search_hard_filters_scope_status_policy_and_provider_egress(
    tmp_path: Path,
) -> None:
    with ExperienceStore((tmp_path / "state.db").resolve()) as store:
        _policy(store)
        _lesson(store, item_id="same-domain")
        _lesson(
            store,
            item_id="different-domain",
            egress_policy="same_provider_trust_domain",
            producer_trust_domain="provider:b",
        )
        _lesson(store, item_id="blocked", sensitivity="blocked")
        _lesson(store, item_id="candidate", status="candidate")
        store.upsert_scope_policy(
            principal_id="local-owner",
            repository_id=REPO_ID,
            project_id="project_other",
            project_root_rel="apps/other",
            recall_allowed=True,
            injection_allowed=True,
            max_egress_policy="explicit_any_provider",
        )
        _lesson(store, item_id="other-project", project_id="project_other")

        assert [item["id"] for item in _search(store)] == ["same-domain"]
        other = _search(store, project_id="project_other", scope_id="project_other")
        assert [item["id"] for item in other] == ["other-project"]
        assert [
            item["id"] for item in _search(store, provider_trust_domain="provider:b")
        ] == ["different-domain"]
        assert {item["id"] for item in _search(store, provider_is_local=True)} == {
            "same-domain",
            "different-domain",
        }

        store.upsert_scope_policy(
            principal_id="local-owner",
            repository_id=REPO_ID,
            project_id=PROJECT_ID,
            project_root_rel="apps/api",
            recall_allowed=True,
            injection_allowed=False,
            max_egress_policy="explicit_any_provider",
        )
        assert _search(store) == []


def test_search_and_reauthorization_require_project_recall_consent(
    tmp_path: Path,
) -> None:
    with ExperienceStore((tmp_path / "state.db").resolve()) as store:
        _policy(store)
        lesson = _lesson(store)
        assert _search(store, require_injection_allowed=False)

        store.upsert_scope_policy(
            principal_id="local-owner",
            repository_id=REPO_ID,
            project_id=PROJECT_ID,
            project_root_rel="apps/api",
            capture_allowed=True,
            recall_allowed=False,
            injection_allowed=True,
            max_egress_policy="explicit_any_provider",
            updated_at=4.0,
        )

        assert _search(store, require_injection_allowed=False) == []
        assert store.authorized_lesson_revisions(
            principal_id="local-owner",
            scope_type="project",
            scope_id=PROJECT_ID,
            repository_id=REPO_ID,
            project_id=PROJECT_ID,
            provider_trust_domain="provider:a",
            candidates=((lesson["id"], lesson["current_revision"]),),
            require_injection_allowed=False,
        ) == set()


def test_list_items_filters_multiple_statuses_in_sql_before_limit(
    tmp_path: Path,
) -> None:
    with ExperienceStore((tmp_path / "state.db").resolve()) as store:
        _policy(store)
        _lesson(store, item_id="lesson_active")
        _lesson(store, item_id="lesson_candidate", status="candidate")
        _lesson(store, item_id="lesson_rejected", status="candidate")
        store.transition_lesson(
            "lesson_rejected", "rejected", transitioned_at=3.0
        )

        filtered = store.list_items(
            status=("candidate", "rejected"),
            limit=2,
        )
        candidate_only = store.list_items(status=("candidate",), limit=1)

    assert {item["current_status"] for item in filtered} == {
        "candidate",
        "rejected",
    }
    assert [item["id"] for item in candidate_only] == ["lesson_candidate"]


def test_search_does_not_cap_or_overflow_large_authorized_candidate_set(
    tmp_path: Path,
) -> None:
    with ExperienceStore((tmp_path / "state.db").resolve()) as store:
        _policy(store)
        for index in range(1_001):
            tags = (
                {"failure": ["late metadata match"]}
                if index == 1_000
                else {"technology": ["bulk fixture"]}
            )
            _lesson(
                store,
                item_id=f"lesson_{index:04d}",
                tags=tags,
            )

        matches = _search(
            store,
            tags={"failure": ["late metadata match"]},
            require_injection_allowed=False,
        )

    assert [item["id"] for item in matches] == ["lesson_1000"]


def test_existing_policy_schema_migrates_recall_consent_as_default_deny(
    tmp_path: Path,
) -> None:
    path = (tmp_path / "state.db").resolve()
    with sqlite3.connect(path) as legacy:
        legacy.execute(
            """
            CREATE TABLE experience_scope_policies (
                principal_id TEXT NOT NULL,
                repository_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                project_root_rel TEXT NOT NULL,
                workspace_root TEXT,
                capture_allowed INTEGER NOT NULL DEFAULT 0,
                injection_allowed INTEGER NOT NULL DEFAULT 0,
                reflection_allowed INTEGER NOT NULL DEFAULT 0,
                max_egress_policy TEXT NOT NULL DEFAULT 'local_only',
                updated_at REAL NOT NULL,
                PRIMARY KEY (principal_id, repository_id, project_id)
            )
            """
        )
        legacy.execute(
            """
            INSERT INTO experience_scope_policies(
                principal_id, repository_id, project_id, project_root_rel,
                capture_allowed, injection_allowed, reflection_allowed,
                max_egress_policy, updated_at
            ) VALUES ('local-owner', ?, ?, 'apps/api', 1, 1, 0,
                      'explicit_any_provider', 1.0)
            """,
            (REPO_ID, PROJECT_ID),
        )

    with ExperienceStore(path) as migrated:
        policy = migrated.get_scope_policy(
            principal_id="local-owner",
            repository_id=REPO_ID,
            project_id=PROJECT_ID,
        )
        assert policy is not None
        assert policy["capture_allowed"] is True
        assert policy["recall_allowed"] is False
        assert policy["injection_allowed"] is True

    with ExperienceStore(path) as reopened:
        assert reopened.get_scope_policy(
            principal_id="local-owner",
            repository_id=REPO_ID,
            project_id=PROJECT_ID,
        )["recall_allowed"] is False

    with sqlite3.connect(path) as raw:
        columns = {
            row[1] for row in raw.execute("PRAGMA table_info(experience_scope_policies)")
        }
        version = raw.execute(
            "SELECT value FROM experience_schema_meta WHERE key = 'version'"
        ).fetchone()[0]
    assert "recall_allowed" in columns
    assert version == "2"


def test_deferred_mutation_surfaces_are_not_exposed() -> None:
    assert not hasattr(ExperienceStore, "add_link")
    assert not hasattr(ExperienceStore, "record_event")
    assert not hasattr(ExperienceStore, "update_retrieval_item")


def test_retrieval_and_item_diagnostics_are_atomic_text_free_and_purge_safe(
    tmp_path: Path,
) -> None:
    with ExperienceStore((tmp_path / "state.db").resolve()) as store:
        _policy(store)
        lesson = _lesson(store)
        result = _search(store)[0]
        retrieval = store.record_retrieval(
            retrieval_id="retrieval_test",
            idempotency_key="retrieval:test",
            turn_id="turn-1",
            work_id="work-1",
            principal_id="local-owner",
            repository_id=REPO_ID,
            project_id=PROJECT_ID,
            task_signature_hash="b" * 64,
            provider_trust_domain="provider:a",
            items=[
                {
                    "item_id": lesson["id"],
                    "item_revision": result["revision"]["revision"],
                    "rank": 1,
                    "score": result["score"],
                    "match_reasons": result["match_reasons"],
                }
            ],
            created_at=10.0,
        )
        replay = store.record_retrieval(
            retrieval_id="retrieval_test",
            idempotency_key="retrieval:test",
            turn_id="turn-1",
            work_id="work-1",
            principal_id="local-owner",
            repository_id=REPO_ID,
            project_id=PROJECT_ID,
            task_signature_hash="b" * 64,
            provider_trust_domain="provider:a",
            items=retrieval["items"],
        )
        assert replay["id"] == retrieval["id"]
        assert "body" not in repr(retrieval)
        latest = store.get_latest_retrieval(
            principal_id="local-owner",
            repository_id=REPO_ID,
            project_id=PROJECT_ID,
        )
        assert latest is not None
        assert latest["id"] == retrieval["id"]
        assert retrieval["items"][0]["disposition"] == "retrieved"
        assert "planned_effect" not in retrieval["items"][0]

        purged = store.purge_item("lesson_test", vacuum=False)
        assert purged["purged"] is True
        assert store.get_item("lesson_test") is None
        remaining = store.get_retrieval("retrieval_test")
        assert remaining is not None and remaining["items"] == []
        assert store.list_events(item_id="lesson_test") == []


def test_session_delete_does_not_cascade_to_experience(tmp_path: Path) -> None:
    path = (tmp_path / "state.db").resolve()
    session_db = SessionDB(path)
    session_db.create_session("source-session", "cli")
    session_db.close()

    with ExperienceStore(path) as store:
        _policy(store)
        _lesson(store)

    session_db = SessionDB(path)
    assert session_db.delete_session("source-session") is True
    session_db.close()

    with ExperienceStore(path) as store:
        assert store.get_item("lesson_test") is not None


def test_concurrent_idempotent_create_retries_to_one_item(tmp_path: Path) -> None:
    path = (tmp_path / "state.db").resolve()
    stores = (ExperienceStore(path), ExperienceStore(path))
    for store in stores:
        _policy(store)
    barrier = threading.Barrier(2)
    results: list[str] = []
    errors: list[BaseException] = []

    def create(store: ExperienceStore) -> None:
        try:
            barrier.wait()
            results.append(_lesson(store, status="candidate")["id"])
        except BaseException as exc:  # surfaced below with its original type
            errors.append(exc)

    threads = [threading.Thread(target=create, args=(store,)) for store in stores]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    try:
        assert errors == []
        assert results == ["lesson_test", "lesson_test"]
        assert len(stores[0].list_items()) == 1
    finally:
        for store in stores:
            store.close()


def test_rejects_nonfinite_diagnostic_scores(tmp_path: Path) -> None:
    with ExperienceStore((tmp_path / "state.db").resolve()) as store:
        _policy(store)
        _lesson(store)
        with pytest.raises(ValueError):
            store.record_retrieval(
                turn_id="turn",
                work_id="work",
                principal_id="local-owner",
                repository_id=REPO_ID,
                project_id=PROJECT_ID,
                task_signature_hash="c" * 64,
                provider_trust_domain="provider:a",
                items=[
                    {
                        "item_id": "lesson_test",
                        "item_revision": 1,
                        "rank": 1,
                        "score": math.inf,
                        "match_reasons": ["project exact"],
                    }
                ],
            )


def test_rejects_credentials_in_identifiers_and_json_keys(tmp_path: Path) -> None:
    secret = "sk-" + ("a1B2c3D4" * 8)
    with ExperienceStore((tmp_path / "state.db").resolve()) as store:
        _policy(store)
        with pytest.raises(ValueError, match="unsafe item_id"):
            store.create_lesson(
                item_id=secret,
                principal_id="local-owner",
                scope_type="project",
                scope_id=PROJECT_ID,
                repository_id=REPO_ID,
                project_id=PROJECT_ID,
                title="Safe title",
                body=_body(),
            )
        with pytest.raises(ValueError, match="unsafe object key"):
            store.create_lesson(
                item_id="lesson_safe_metadata",
                principal_id="local-owner",
                scope_type="project",
                scope_id=PROJECT_ID,
                repository_id=REPO_ID,
                project_id=PROJECT_ID,
                title="Safe title",
                body=_body(),
                producer={secret: "value"},
            )


def test_idempotency_keys_reject_semantically_different_replays(tmp_path: Path) -> None:
    with ExperienceStore((tmp_path / "state.db").resolve()) as store:
        _policy(store)
        lesson = _lesson(store, status="candidate")

        with pytest.raises(ValueError, match="another lesson"):
            store.create_lesson(
                item_id="lesson_different",
                idempotency_key="create:lesson_test",
                principal_id="local-owner",
                scope_type="project",
                scope_id=PROJECT_ID,
                repository_id=REPO_ID,
                project_id=PROJECT_ID,
                title="Lesson lesson_test",
                summary="A bounded, manually curated lesson.",
                body=_body(),
                tags={"technology": ["sqlite"], "task_type": ["persistence"]},
                confidence=0.8,
                sensitivity="normal",
                egress_policy="same_provider_trust_domain",
                producer_trust_domain="provider:a",
                created_by="user",
                source_session_id="source-session",
                source_turn_id="source-turn",
                source_work_id="source-work",
                source_hash="a" * 64,
            )

        store.approve_lesson(
            lesson["id"],
            actor="user",
            reason="reviewed",
            idempotency_key="transition:lesson_test:active",
            transitioned_at=3.0,
        )
        # An exact replay is a no-op even though the lesson is already active.
        assert store.approve_lesson(
            lesson["id"],
            actor="user",
            reason="reviewed",
            idempotency_key="transition:lesson_test:active",
            transitioned_at=4.0,
        )["current_status"] == "active"
        with pytest.raises(ValueError, match="another transition"):
            store.approve_lesson(
                lesson["id"],
                actor="user",
                reason="different approval",
                idempotency_key="transition:lesson_test:active",
                transitioned_at=4.0,
            )

        result = _search(store)[0]
        retrieval_items = [
            {
                "item_id": lesson["id"],
                "item_revision": result["revision"]["revision"],
                "rank": 1,
                "score": result["score"],
                "match_reasons": result["match_reasons"],
            }
        ]
        store.record_retrieval(
            retrieval_id="retrieval_collision",
            idempotency_key="retrieval:collision",
            turn_id="turn-collision",
            work_id="work-collision",
            principal_id="local-owner",
            repository_id=REPO_ID,
            project_id=PROJECT_ID,
            task_signature_hash="d" * 64,
            provider_trust_domain="provider:a",
            items=retrieval_items,
        )
        changed_items = [dict(retrieval_items[0], score=result["score"] + 1.0)]
        with pytest.raises(ValueError, match="different items"):
            store.record_retrieval(
                retrieval_id="retrieval_collision",
                idempotency_key="retrieval:collision",
                turn_id="turn-collision",
                work_id="work-collision",
                principal_id="local-owner",
                repository_id=REPO_ID,
                project_id=PROJECT_ID,
                task_signature_hash="d" * 64,
                provider_trust_domain="provider:a",
                items=changed_items,
            )

def test_mutations_reject_backdated_timestamps(tmp_path: Path) -> None:
    with ExperienceStore((tmp_path / "state.db").resolve()) as store:
        _policy(store)
        _lesson(store, status="candidate")

        with pytest.raises(ValueError, match="transitioned_at must be newer"):
            store.approve_lesson("lesson_test", transitioned_at=2.0)

        store.approve_lesson("lesson_test", transitioned_at=3.0)
        with pytest.raises(ValueError, match="edited_at must be newer"):
            store.edit_lesson(
                "lesson_test",
                body=_body("A backdated mutation must not be accepted."),
                edited_at=2.5,
            )
