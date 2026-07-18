"""Typed orchestration for the Work Experience validation MVP.

This module has no agent-loop integration and performs no capture or model
reflection.  It turns one already-scoped, already-separated user request into
an authorized retrieval, records text-free diagnostics, and formats an
advisory block that a later runtime integration may attach to a wire-only copy
of the current user message.
"""

from __future__ import annotations

import hashlib
import html
import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from agent.experience.models import (
    LOCAL_OWNER_PRINCIPAL,
    LessonBody,
    LessonTag,
    RetrievalDiagnostic,
    RetrievalDisposition,
    RetrievalItemDiagnostic,
    RetrievalMatch,
    RetrievalQuery,
    ScopePolicy,
    TagNamespace,
)
from agent.experience.safety import is_egress_allowed, sanitize_for_return
from agent.experience.scope import ResolvedScope, ScopeResolver
from agent.experience.store import ExperienceStore


_LOCAL_TRUST_DOMAIN = "local-runtime"


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Authorized lesson text plus the text-free diagnostic that names it."""

    diagnostic: RetrievalDiagnostic
    query: RetrievalQuery
    items: tuple[RetrievalMatch, ...]
    item_diagnostics: tuple[RetrievalItemDiagnostic, ...]
    fts_enabled: bool
    disclosures: tuple["RetrievalDisclosure", ...] = ()


@dataclass(frozen=True, slots=True)
class RetrievalDisclosure:
    """Immutable item policy retained for per-request fallback checks."""

    item_id: str
    item_revision: int
    sensitivity: str
    egress_policy: str
    producer_trust_domain: str | None


class ExperienceService:
    """Retrieve and format manually approved work-experience lessons.

    Callers remain responsible for supplying only the explicit raw request
    text, not rendered attachments, diffs, fetched pages, or skill content.
    The service stores only its deterministic hash.
    """

    def __init__(
        self,
        store: ExperienceStore,
        *,
        scope_resolver: ScopeResolver | None = None,
        max_retrieved_items: int = 3,
        max_context_chars: int = 1_500,
        min_confidence: float = 0.0,
    ) -> None:
        if not isinstance(store, ExperienceStore):
            raise TypeError("store must be an ExperienceStore")
        if not 1 <= int(max_retrieved_items) <= 50:
            raise ValueError("max_retrieved_items must be between 1 and 50")
        if not 256 <= int(max_context_chars) <= 16_384:
            raise ValueError("max_context_chars must be between 256 and 16384")
        if not 0.0 <= float(min_confidence) <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        self.store = store
        self.scope_resolver = scope_resolver
        self.max_retrieved_items = int(max_retrieved_items)
        self.max_context_chars = int(max_context_chars)
        self.min_confidence = float(min_confidence)

    @contextmanager
    def _available_store(self) -> Iterator[ExperienceStore]:
        """Yield the owned facade or reopen its explicit profile DB briefly.

        Runtime integration may cache a frozen retrieval after its setup
        transaction has closed. Governance checks and declarations must still
        consult current state, so those operations reopen the same explicit
        database rather than trusting cached authorization.
        """

        if not self.store.closed:
            yield self.store
            return
        with ExperienceStore(
            self.store.db_path,
            initialize_schema=False,
        ) as reopened:
            yield reopened

    def resolve_scope(self, cwd: str) -> ResolvedScope:
        """Resolve the most-specific stored policy for a logical runtime cwd."""

        if self.scope_resolver is None:
            raise RuntimeError("scope_resolver is required to resolve a cwd")
        policies = self.store.list_scope_policies(
            principal_id=LOCAL_OWNER_PRINCIPAL
        )
        return self.scope_resolver.resolve(cwd, policies)

    @staticmethod
    def task_signature_hash(query: RetrievalQuery) -> str:
        """Return stable metadata for diagnostics without persisting raw text."""

        payload = {
            "query": query.query_text,
            "scope": {
                "principal": query.scope.principal_id,
                "type": query.scope.scope_type.value,
                "id": query.scope.scope_id,
                "repository": query.scope.repository_id,
                "project": query.scope.project_id,
            },
            "task_types": query.task_types,
            "technologies": query.technologies,
            "entities": query.entities,
            "failure_fingerprints": query.failure_fingerprints,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _retrieval_id(
        *,
        turn_id: str,
        work_id: str,
        signature_hash: str,
        query: RetrievalQuery,
    ) -> str:
        material = "\0".join(
            (
                turn_id,
                work_id,
                signature_hash,
                query.scope.principal_id,
                query.scope.scope_id,
                query.provider_trust_domain or _LOCAL_TRUST_DOMAIN,
                "local" if query.provider_is_local else "remote",
            )
        )
        return "retrieval_" + hashlib.sha256(material.encode()).hexdigest()[:32]

    @staticmethod
    def _query_tags(query: RetrievalQuery) -> dict[str, tuple[str, ...]]:
        return {
            TagNamespace.TASK_TYPE.value: query.task_types,
            TagNamespace.TECHNOLOGY.value: query.technologies,
            TagNamespace.ENTITY.value: query.entities,
            TagNamespace.FAILURE.value: query.failure_fingerprints,
        }

    @staticmethod
    def _match_from_mapping(
        value: Mapping[str, Any],
        *,
        rank: int,
    ) -> RetrievalMatch:
        revision = value["revision"]
        tags = tuple(
            LessonTag(TagNamespace(tag["namespace"]), tag["value"])
            for tag in revision.get("tags", ())
        )
        return RetrievalMatch(
            item_id=value["id"],
            item_revision=int(revision["revision"]),
            title=revision["title"],
            summary=revision["summary"],
            body=LessonBody.from_mapping(revision["body"]),
            rank=rank,
            score=float(value["score"]),
            match_reasons=tuple(value["match_reasons"]),
            confidence=revision.get("confidence"),
            tags=tags,
        )

    def retrieve(
        self,
        query: RetrievalQuery,
        *,
        turn_id: str,
        work_id: str,
        retrieval_id: str | None = None,
        idempotency_key: str | None = None,
        require_injection_allowed: bool = True,
    ) -> RetrievalResult:
        """Run one authorized search and atomically record its diagnostics."""

        if not isinstance(query, RetrievalQuery):
            raise TypeError("query must be a RetrievalQuery")
        if not isinstance(require_injection_allowed, bool):
            raise TypeError("require_injection_allowed must be bool")
        signature_hash = self.task_signature_hash(query)
        provider_domain = query.provider_trust_domain or _LOCAL_TRUST_DOMAIN
        limit = min(query.limit, self.max_retrieved_items)
        rows = self.store.search_lessons(
            principal_id=query.scope.principal_id,
            scope_type=query.scope.scope_type,
            scope_id=query.scope.scope_id,
            repository_id=query.scope.repository_id,
            project_id=query.scope.project_id,
            provider_trust_domain=provider_domain,
            provider_is_local=query.provider_is_local,
            query=query.query_text,
            tags=self._query_tags(query),
            min_confidence=self.min_confidence,
            require_injection_allowed=require_injection_allowed,
            limit=limit,
        )

        policy = None
        if query.scope.repository_id and query.scope.project_id:
            raw_policy = self.store.get_scope_policy(
                principal_id=query.scope.principal_id,
                repository_id=query.scope.repository_id,
                project_id=query.scope.project_id,
            )
            if raw_policy is not None:
                policy = ScopePolicy.from_mapping(raw_policy)

        matches: list[RetrievalMatch] = []
        disclosures: list[RetrievalDisclosure] = []
        for row in rows:
            # Defense in depth: SQL performs this check before selecting any
            # revision text.  Re-check here so a future store cannot weaken
            # the typed service boundary accidentally.
            if policy is None or not is_egress_allowed(
                sensitivity=row["sensitivity"],
                egress_policy=row["egress_policy"],
                producer_trust_domain=row.get("producer_trust_domain"),
                current_trust_domain=provider_domain,
                current_provider_is_local=query.provider_is_local,
                max_egress_policy=policy.max_egress_policy,
            ):
                continue
            match = self._match_from_mapping(row, rank=len(matches) + 1)
            matches.append(match)
            disclosures.append(
                RetrievalDisclosure(
                    item_id=match.item_id,
                    item_revision=match.item_revision,
                    sensitivity=str(row["sensitivity"]),
                    egress_policy=str(row["egress_policy"]),
                    producer_trust_domain=row.get("producer_trust_domain"),
                )
            )

        resolved_retrieval_id = retrieval_id or self._retrieval_id(
            turn_id=turn_id,
            work_id=work_id,
            signature_hash=signature_hash,
            query=query,
        )
        stored = self.store.record_retrieval(
            retrieval_id=resolved_retrieval_id,
            idempotency_key=idempotency_key or resolved_retrieval_id,
            turn_id=turn_id,
            work_id=work_id,
            principal_id=query.scope.principal_id,
            repository_id=query.scope.repository_id or "profile",
            project_id=query.scope.project_id or query.scope.scope_id,
            task_signature_hash=signature_hash,
            provider_trust_domain=provider_domain,
            items=[
                {
                    "item_id": match.item_id,
                    "item_revision": match.item_revision,
                    "rank": match.rank,
                    "score": match.score,
                    "match_reasons": match.match_reasons,
                }
                for match in matches
            ],
        )
        diagnostic = RetrievalDiagnostic(
            id=stored["id"],
            turn_id=stored["turn_id"],
            work_id=stored["work_id"],
            principal_id=stored["principal_id"],
            repository_id=stored["repository_id"],
            project_id=stored["project_id"],
            task_signature_hash=stored["task_signature_hash"],
            provider_trust_domain=stored["provider_trust_domain"],
            created_at=stored["created_at"],
        )
        item_diagnostics = tuple(
            RetrievalItemDiagnostic(
                retrieval_id=item["retrieval_id"],
                item_id=item["item_id"],
                item_revision=item["item_revision"],
                rank=item["rank"],
                score=item["score"],
                match_reasons=tuple(item["match_reasons"]),
                disposition=RetrievalDisposition(item["disposition"]),
            )
            for item in stored["items"]
        )
        return RetrievalResult(
            diagnostic=diagnostic,
            query=query,
            items=tuple(matches),
            item_diagnostics=item_diagnostics,
            fts_enabled=self.store.fts_enabled,
            disclosures=tuple(disclosures),
        )

    def format_context(
        self,
        result: RetrievalResult,
        *,
        max_chars: int | None = None,
        provider_trust_domain: str | None = None,
        provider_is_local: bool | None = None,
    ) -> str:
        """Build bounded advice after rechecking current policy and provider.

        The optional provider fields are for a fallback request whose egress
        identity differs from the provider used to rank the cached result.
        """

        if not result.items:
            return ""
        budget = self.max_context_chars if max_chars is None else int(max_chars)
        if not 256 <= budget <= 16_384:
            raise ValueError("max_chars must be between 256 and 16384")
        opening = (
            "<work-experience-context>\n"
            f"retrieval_ref: {html.escape(result.diagnostic.id[:24])}\n"
            "Historical, fallible evidence. Current user instructions, repository "
            "state, tests, and project policy take precedence.\n"
        )
        closing = "</work-experience-context>"
        # Ranking and sanitized text are frozen for this turn, but governance
        # is not. Revalidate only the selected IDs/revisions immediately before
        # model-visible text is built. This avoids repeating FTS on every tool
        # iteration while making retraction, policy revocation, revision
        # changes, and provider fallback effective immediately.
        current_is_local = (
            result.query.provider_is_local
            if provider_is_local is None
            else provider_is_local
        )
        if not isinstance(current_is_local, bool):
            raise TypeError("provider_is_local must be bool")
        current_domain = (
            provider_trust_domain
            if provider_trust_domain is not None
            else result.query.provider_trust_domain
        )
        if current_is_local and current_domain is None:
            current_domain = _LOCAL_TRUST_DOMAIN
        if not current_is_local and not current_domain:
            return ""
        with self._available_store() as store:
            still_authorized = store.authorized_lesson_revisions(
                principal_id=result.query.scope.principal_id,
                scope_type=result.query.scope.scope_type,
                scope_id=result.query.scope.scope_id,
                repository_id=result.query.scope.repository_id,
                project_id=result.query.scope.project_id,
                provider_trust_domain=current_domain,
                provider_is_local=current_is_local,
                candidates=(
                    (item.item_id, item.item_revision) for item in result.items
                ),
                require_injection_allowed=True,
            )
        eligible_items = tuple(
            item
            for item in result.items
            if (item.item_id, item.item_revision) in still_authorized
        )
        if not eligible_items:
            return ""
        chunks: list[str] = []
        remaining = budget - len(opening) - len(closing) - 1
        for item in eligible_items:
            chunk = self._format_item(item, max_chars=max(96, remaining))
            needed = len(chunk) + (1 if chunks else 0)
            if needed > remaining:
                break
            chunks.append(chunk)
            remaining -= needed
        if not chunks:
            return ""
        rendered = opening + "\n".join(chunks) + "\n" + closing
        # Stored fields were already sanitized on read.  Repeat the complete
        # boundary after framing in case delimiters interact with old content.
        return sanitize_for_return(rendered, max_chars=budget)

    @staticmethod
    def _format_item(item: RetrievalMatch, *, max_chars: int) -> str:
        confidence = (
            "unknown" if item.confidence is None else f"{item.confidence:.2f}"
        )
        lines = [
            f"[lesson {html.escape(item.item_id[:24])} rev={item.item_revision} "
            f"status=active confidence={confidence}]",
            "applies_when: " + html.escape(item.body.applies_when),
            "guidance: " + html.escape(item.body.guidance),
            "rationale: " + html.escape(item.body.rationale),
            "match: " + html.escape("; ".join(item.match_reasons)),
        ]
        if item.body.does_not_apply_when:
            lines.insert(
                2,
                "does_not_apply_when: "
                + html.escape(item.body.does_not_apply_when),
            )
        rendered = "\n".join(lines)
        if len(rendered) <= max_chars:
            return rendered
        # Keep a structurally complete item and favor trigger/guidance over
        # rationale when the configured context budget is tight.
        compact = "\n".join(
            (
                lines[0],
                "applies_when: " + html.escape(item.body.applies_when),
                "guidance: " + html.escape(item.body.guidance),
                lines[-1],
            )
        )
        if len(compact) <= max_chars:
            return compact
        return compact[: max(0, max_chars - 1)].rstrip() + "…"


__all__ = ["ExperienceService", "RetrievalDisclosure", "RetrievalResult"]
