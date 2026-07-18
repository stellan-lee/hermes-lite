from __future__ import annotations

from pathlib import Path

from agent.experience.models import RetrievalQuery, ScopeRef, ScopeType
from agent.experience.service import ExperienceService
from agent.experience.store import ExperienceStore


def _seed(store: ExperienceStore) -> ScopeRef:
    store.upsert_scope_policy(
        principal_id="local-owner",
        repository_id="repo",
        project_id="project",
        project_root_rel="apps/api",
        recall_allowed=True,
        injection_allowed=True,
        max_egress_policy="same_provider_trust_domain",
    )
    store.create_lesson(
        item_id="lesson",
        principal_id="local-owner",
        scope_type="project",
        scope_id="project",
        repository_id="repo",
        project_id="project",
        title="Avoid synchronized SQLite retries",
        summary="Use bounded jitter for contending writers.",
        body={
            "applies_when": "SQLite returns database is locked",
            "does_not_apply_when": "Only one writer exists",
            "guidance": "Use <BEGIN IMMEDIATE> and bounded random jitter.",
            "rationale": "Deterministic retry intervals form a convoy.",
        },
        tags={
            "technology": ["sqlite"],
            "task_type": ["persistence"],
            "failure": ["database is locked"],
        },
        confidence=0.9,
        sensitivity="private_repo",
        egress_policy="same_provider_trust_domain",
        producer_trust_domain="provider:a",
    )
    store.approve_lesson("lesson")
    return ScopeRef(
        principal_id="local-owner",
        scope_type=ScopeType.PROJECT,
        scope_id="project",
        repository_id="repo",
        project_id="project",
    )


def _query(scope: ScopeRef, *, provider: str = "provider:a") -> RetrievalQuery:
    return RetrievalQuery(
        scope=scope,
        query_text="Fix SQLite writer contention",
        provider_trust_domain=provider,
        technologies=("sqlite",),
        task_types=("persistence",),
        failure_fingerprints=("database is locked",),
    )


def test_deferred_application_api_is_not_exposed() -> None:
    assert not hasattr(ExperienceService, "declare_applied")


def test_service_retrieves_records_diagnostics_and_formats_bounded_advice(
    tmp_path: Path,
) -> None:
    with ExperienceStore((tmp_path / "state.db").resolve()) as store:
        scope = _seed(store)
        service = ExperienceService(store, max_context_chars=600)

        result = service.retrieve(
            _query(scope),
            turn_id="turn-1",
            work_id="work-1",
        )

        assert [item.item_id for item in result.items] == ["lesson"]
        assert result.item_diagnostics[0].match_reasons[0] == "project exact"
        stored = store.get_retrieval(result.diagnostic.id)
        assert stored is not None
        assert "Fix SQLite" not in repr(stored)
        assert stored["task_signature_hash"] == result.diagnostic.task_signature_hash

        context = service.format_context(result)
        assert len(context) <= 600
        assert context.startswith("<work-experience-context")
        assert "Historical, fallible evidence" in context
        assert "&lt;BEGIN IMMEDIATE&gt;" in context
        assert context.endswith("</work-experience-context>")


def test_provider_change_and_retraction_fail_closed(tmp_path: Path) -> None:
    with ExperienceStore((tmp_path / "state.db").resolve()) as store:
        scope = _seed(store)
        service = ExperienceService(store)

        wrong_provider = service.retrieve(
            _query(scope, provider="provider:b"),
            turn_id="turn-b",
            work_id="work-b",
        )
        assert wrong_provider.items == ()
        assert wrong_provider.item_diagnostics == ()
        assert service.format_context(wrong_provider) == ""

        previously_authorized = service.retrieve(
            _query(scope),
            turn_id="turn-authorized",
            work_id="work-authorized",
        )
        assert previously_authorized.items
        store.retract_lesson("lesson", reason="Superseded by current evidence")
        assert service.format_context(previously_authorized) == ""
        retracted = service.retrieve(
            _query(scope),
            turn_id="turn-c",
            work_id="work-c",
        )
        assert retracted.items == ()


def test_task_signature_metadata_is_deterministic_and_text_is_not_stored(
    tmp_path: Path,
) -> None:
    with ExperienceStore((tmp_path / "state.db").resolve()) as store:
        scope = _seed(store)
        query = _query(scope)
        service = ExperienceService(store)

        first = service.retrieve(query, turn_id="turn", work_id="work")
        second = service.retrieve(query, turn_id="turn", work_id="work")

        assert first.diagnostic.id == second.diagnostic.id
        assert first.diagnostic.task_signature_hash == second.diagnostic.task_signature_hash
        assert store.diagnostic_stats()["retrieval_count"] == 1


def test_shadow_retrieval_does_not_require_injection_permission(tmp_path: Path) -> None:
    with ExperienceStore((tmp_path / "state.db").resolve()) as store:
        scope = _seed(store)
        store.upsert_scope_policy(
            principal_id="local-owner",
            repository_id="repo",
            project_id="project",
            project_root_rel="apps/api",
            capture_allowed=True,
            recall_allowed=True,
            injection_allowed=False,
            max_egress_policy="same_provider_trust_domain",
        )
        service = ExperienceService(store)

        shadow = service.retrieve(
            _query(scope),
            turn_id="turn-shadow",
            work_id="work-shadow",
            require_injection_allowed=False,
        )
        assist = service.retrieve(
            _query(scope),
            turn_id="turn-assist",
            work_id="work-assist",
            require_injection_allowed=True,
        )

        assert [item.item_id for item in shadow.items] == ["lesson"]
        assert assist.items == ()
