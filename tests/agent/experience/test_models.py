from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent.experience.models import (
    EgressPolicy,
    LessonBody,
    LessonRevision,
    LessonStatus,
    LessonTag,
    ScopePolicy,
    ScopeRef,
    ScopeType,
    TagNamespace,
    can_transition_lesson,
    lesson_content_hash,
    require_lesson_transition,
)


def test_candidate_is_canonical_and_proposed_is_only_an_input_alias() -> None:
    assert LessonStatus("candidate") is LessonStatus.CANDIDATE
    assert LessonStatus("proposed") is LessonStatus.CANDIDATE
    assert LessonStatus.PROPOSED.value == "candidate"


def test_lesson_lifecycle_is_forward_only_and_replay_safe() -> None:
    assert can_transition_lesson("candidate", "active")
    assert can_transition_lesson("candidate", "rejected")
    assert can_transition_lesson("active", "disputed")
    assert can_transition_lesson("disputed", "deprecated")
    assert can_transition_lesson("active", "active")

    for terminal in ("deprecated", "rejected", "retracted"):
        assert can_transition_lesson(terminal, terminal)
        assert not can_transition_lesson(terminal, "active")

    with pytest.raises(ValueError, match="invalid lesson transition"):
        require_lesson_transition("retracted", "active")


def test_revision_content_and_evidence_metadata_are_immutable() -> None:
    revision = LessonRevision(
        item_id="les_example",
        revision=1,
        title="Use the focused verification path",
        summary="The focused test runner avoids unrelated failures.",
        body=LessonBody(
            applies_when="Changing the experience persistence core",
            does_not_apply_when="A full release gate was requested",
            guidance="Run the focused repository test target.",
            rationale="It keeps the validation signal attributable.",
        ),
        confidence=0.8,
        source_session_id="session-1",
        source_turn_id="turn-1",
        source_work_id="work-1",
        source_hash="a" * 64,
        tags=(
            LessonTag(TagNamespace.TECHNOLOGY, "SQLite"),
            LessonTag(TagNamespace.TASK_TYPE, "Persistence"),
        ),
        producer_metadata=(("provider", "test-provider"),),
        created_at=1.0,
        last_validated_at=2.0,
    )

    assert revision.content_hash == lesson_content_hash(
        revision.body,
        title=revision.title,
        summary=revision.summary,
        tags=revision.tags,
    )
    assert revision.tags == tuple(sorted(revision.tags))
    with pytest.raises(FrozenInstanceError):
        revision.revision = 2  # type: ignore[misc]


def test_scope_rejects_cross_owner_and_incomplete_project_identity() -> None:
    with pytest.raises(ValueError, match="local-owner"):
        ScopeRef("another-user", ScopeType.PROFILE, "profile")
    with pytest.raises(ValueError, match="project scope"):
        ScopeRef("local-owner", ScopeType.PROJECT, "project")

    scope = ScopeRef(
        "local-owner",
        ScopeType.PROJECT,
        "project:abc",
        repository_id="repo:abc",
        project_id="project:abc",
    )
    assert scope.scope_type is ScopeType.PROJECT
    assert EgressPolicy.LOCAL_ONLY.value == "local_only"


def test_scope_ids_must_match_their_authorization_axis() -> None:
    with pytest.raises(ValueError, match="scope_id"):
        ScopeRef(
            "local-owner",
            ScopeType.PROJECT,
            "project:forged",
            repository_id="repo:abc",
            project_id="project:abc",
        )
    with pytest.raises(ValueError, match="only repository_id"):
        ScopeRef(
            "local-owner",
            ScopeType.REPOSITORY,
            "repo:abc",
            repository_id="repo:abc",
            project_id="project:abc",
        )


def test_scope_policy_recall_consent_defaults_denied_and_round_trips() -> None:
    denied = ScopePolicy(
        principal_id="local-owner",
        repository_id="repo:abc",
        project_id="project:abc",
        project_root_rel=".",
    )
    assert denied.recall_allowed is False

    allowed = ScopePolicy.from_mapping(
        {
            **denied.to_dict(),
            "capture_allowed": True,
            "recall_allowed": True,
        }
    )
    assert allowed.recall_allowed is True
    assert allowed.to_dict()["recall_allowed"] is True

    legacy = denied.to_dict()
    legacy.pop("recall_allowed")
    assert ScopePolicy.from_mapping(legacy).recall_allowed is False


def test_lesson_body_mapping_rejects_untyped_extra_fields() -> None:
    with pytest.raises(ValueError, match="unknown lesson body fields"):
        LessonBody.from_mapping(
            {
                **LessonBody("when", "guidance", "rationale").to_dict(),
                "raw_tool_output": "must never become model-visible",
            }
        )
