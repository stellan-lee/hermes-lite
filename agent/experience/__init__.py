"""Public core API for Hermes Work Experience validation.

The package is intentionally integration-neutral: callers explicitly resolve
profile storage and scope, then opt into retrieval.  Nothing here captures a
conversation, invokes a model, or mutates the agent loop.
"""

from agent.experience.models import (
    CreatedBy,
    EgressPolicy,
    Lesson,
    LessonBody,
    LessonRevision,
    LessonStatus,
    LessonTag,
    RetrievalDiagnostic,
    RetrievalDisposition,
    RetrievalItemDiagnostic,
    RetrievalMatch,
    RetrievalQuery,
    ScopePolicy,
    ScopeRef,
    ScopeType,
    Sensitivity,
    TagNamespace,
)
from agent.experience.safety import (
    ExperienceEgressError,
    ExperienceSafety,
    ExperienceSafetyError,
    ExperienceThreatError,
)
from agent.experience.scope import (
    AmbiguousScopeError,
    GitDiscoveryError,
    InvalidScopePolicyError,
    ResolvedScope,
    ScopeNotConfiguredError,
    ScopeResolutionError,
    ScopeResolver,
)
from agent.experience.service import ExperienceService, RetrievalResult
from agent.experience.store import ExperienceStore

__all__ = [
    "AmbiguousScopeError",
    "CreatedBy",
    "EgressPolicy",
    "ExperienceEgressError",
    "ExperienceSafety",
    "ExperienceSafetyError",
    "ExperienceService",
    "ExperienceStore",
    "ExperienceThreatError",
    "GitDiscoveryError",
    "InvalidScopePolicyError",
    "Lesson",
    "LessonBody",
    "LessonRevision",
    "LessonStatus",
    "LessonTag",
    "ResolvedScope",
    "RetrievalDiagnostic",
    "RetrievalDisposition",
    "RetrievalItemDiagnostic",
    "RetrievalMatch",
    "RetrievalQuery",
    "RetrievalResult",
    "ScopeNotConfiguredError",
    "ScopePolicy",
    "ScopeRef",
    "ScopeResolutionError",
    "ScopeResolver",
    "ScopeType",
    "Sensitivity",
    "TagNamespace",
]
