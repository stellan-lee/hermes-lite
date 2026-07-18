"""Fail-closed project scope resolution for work experience.

The resolver never infers consent from the current directory.  It discovers a
repository/workspace identity, then selects only among explicit
:class:`~agent.experience.models.ScopePolicy` records.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from agent.experience.models import (
    EgressPolicy,
    LOCAL_OWNER_PRINCIPAL,
    ScopePolicy,
    ScopeRef,
    ScopeType,
)


class ScopeResolutionError(RuntimeError):
    """Base class for expected, payload-free scope failures."""

    code = "scope_resolution_failed"


class ScopeNotConfiguredError(ScopeResolutionError):
    code = "scope_not_configured"


class AmbiguousScopeError(ScopeResolutionError):
    code = "ambiguous_scope"


class InvalidScopePolicyError(ScopeResolutionError):
    code = "invalid_scope_policy"


class GitDiscoveryError(ScopeResolutionError):
    code = "git_discovery_failed"


def _canonical_directory(path: str | Path, name: str) -> Path:
    candidate = Path(path).expanduser()
    try:
        candidate = candidate.resolve(strict=True)
    except OSError as exc:
        raise ScopeResolutionError(f"{name} is unavailable") from exc
    if not candidate.is_dir():
        raise ScopeResolutionError(f"{name} is not a directory")
    return candidate


def normalize_project_root_rel(value: str | Path) -> str:
    """Return a safe POSIX repository-relative project root."""

    raw = os.fspath(value).strip()
    if not raw or "\x00" in raw or "\\" in raw:
        raise InvalidScopePolicyError("project root must be a non-empty POSIX path")
    rel = PurePosixPath(raw)
    if rel.is_absolute() or ".." in rel.parts:
        raise InvalidScopePolicyError("project root must remain inside the repository")
    return rel.as_posix() or "."


def _profile_key(profile_namespace: str | bytes) -> bytes:
    value = profile_namespace if isinstance(profile_namespace, bytes) else profile_namespace.encode()
    if not value:
        raise ValueError("profile_namespace must be explicit and non-empty")
    return hashlib.sha256(b"hermes-experience-profile\0" + value).digest()


def _path_identity(prefix: str, path: Path, profile_namespace: str | bytes) -> str:
    canonical = os.path.normcase(str(path.resolve(strict=True))).encode("utf-8", "surrogatepass")
    digest = hmac.new(_profile_key(profile_namespace), canonical, hashlib.sha256).hexdigest()
    return f"{prefix}_{digest}"


def repository_id_from_common_dir(
    common_dir: str | Path,
    profile_namespace: str | bytes,
) -> str:
    """Create a profile-local repository ID from Git's common directory."""

    return _path_identity("repo", _canonical_directory(common_dir, "Git common directory"), profile_namespace)


def workspace_id_from_root(
    workspace_root: str | Path,
    profile_namespace: str | bytes,
) -> str:
    """Create a profile-local ID for an explicit non-Git workspace root."""

    return _path_identity("workspace", _canonical_directory(workspace_root, "workspace root"), profile_namespace)


def project_id_for_repository(repository_id: str, project_root_rel: str | Path) -> str:
    """Create a stable project ID from repository identity and configured root."""

    rel = normalize_project_root_rel(project_root_rel)
    digest = hashlib.sha256(f"{repository_id}\0{rel}".encode()).hexdigest()
    return f"project_{digest}"


@dataclass(frozen=True, slots=True)
class GitContext:
    """Canonical paths returned by Git plus the profile-local repository ID."""

    repository_root: Path
    common_dir: Path
    repository_id: str


@dataclass(frozen=True, slots=True)
class ResolvedScope:
    """One unambiguous policy-backed project scope."""

    principal_id: str
    repository_id: str
    project_id: str
    project_root: Path
    policy: ScopePolicy
    repository_root: Path | None = None
    git_common_dir: Path | None = None
    workspace_root: Path | None = None

    @property
    def scope_type(self) -> ScopeType:
        return ScopeType.PROJECT

    @property
    def scope_id(self) -> str:
        return self.project_id

    @property
    def is_workspace(self) -> bool:
        return self.workspace_root is not None

    def as_ref(self) -> ScopeRef:
        """Return the persistence-safe authorization identifiers only."""

        return ScopeRef(
            principal_id=self.principal_id,
            scope_type=ScopeType.PROJECT,
            scope_id=self.project_id,
            repository_id=self.repository_id,
            project_id=self.project_id,
        )


class ScopeResolver:
    """Resolve Git projects and explicit non-Git workspaces for one profile."""

    def __init__(
        self,
        profile_namespace: str | bytes,
        *,
        principal_id: str = LOCAL_OWNER_PRINCIPAL,
        git_timeout_seconds: float = 5.0,
    ) -> None:
        if principal_id != LOCAL_OWNER_PRINCIPAL:
            raise ValueError("the validation MVP supports only local-owner")
        self._profile_namespace = profile_namespace
        _profile_key(profile_namespace)
        self.principal_id = principal_id
        self.git_timeout_seconds = git_timeout_seconds

    def discover_git(self, cwd: str | Path) -> GitContext | None:
        """Discover the nearest Git worktree without reading remote URLs."""

        cwd_path = _canonical_directory(cwd, "runtime cwd")
        command = [
            "git",
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
            "--git-common-dir",
        ]
        try:
            # Repository-shaping Git environment variables can redirect
            # discovery away from ``cwd``. Experience authorization must be
            # derived from the logical runtime directory alone.
            clean_env = {
                key: value
                for key, value in os.environ.items()
                if not key.upper().startswith("GIT_")
            }
            result = subprocess.run(
                command,
                cwd=cwd_path,
                env=clean_env,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.git_timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            if _has_git_marker(cwd_path):
                raise GitDiscoveryError("Git repository identity could not be verified") from exc
            return None
        if result.returncode != 0:
            if _has_git_marker(cwd_path):
                raise GitDiscoveryError("Git repository identity could not be verified")
            return None
        lines = result.stdout.splitlines()
        if len(lines) != 2:
            raise GitDiscoveryError("Git returned an ambiguous repository identity")
        repository_root = _canonical_directory(lines[0], "repository root")
        common_dir = _canonical_directory(lines[1], "Git common directory")
        return GitContext(
            repository_root=repository_root,
            common_dir=common_dir,
            repository_id=repository_id_from_common_dir(common_dir, self._profile_namespace),
        )

    def make_git_policy(
        self,
        cwd: str | Path,
        project_root: str | Path,
        *,
        capture_allowed: bool = False,
        recall_allowed: bool = False,
        injection_allowed: bool = False,
        reflection_allowed: bool = False,
        max_egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY,
        updated_at: float = 0.0,
    ) -> ScopePolicy:
        """Build a policy for an explicit directory in the discovered worktree."""

        git = self.discover_git(cwd)
        if git is None:
            raise InvalidScopePolicyError("a Git project policy requires a Git worktree")
        raw_root = Path(project_root).expanduser()
        root = raw_root if raw_root.is_absolute() else git.repository_root / raw_root
        root = _canonical_directory(root, "project root")
        try:
            rel = normalize_project_root_rel(root.relative_to(git.repository_root).as_posix())
        except ValueError as exc:
            raise InvalidScopePolicyError("project root is outside the worktree") from exc
        return ScopePolicy(
            principal_id=self.principal_id,
            repository_id=git.repository_id,
            project_id=project_id_for_repository(git.repository_id, rel),
            project_root_rel=rel,
            capture_allowed=capture_allowed,
            recall_allowed=recall_allowed,
            injection_allowed=injection_allowed,
            reflection_allowed=reflection_allowed,
            max_egress_policy=max_egress_policy,
            updated_at=updated_at,
        )

    def make_workspace_policy(
        self,
        workspace_root: str | Path,
        *,
        capture_allowed: bool = False,
        recall_allowed: bool = False,
        injection_allowed: bool = False,
        reflection_allowed: bool = False,
        max_egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY,
        updated_at: float = 0.0,
    ) -> ScopePolicy:
        """Build a policy for an explicit canonical directory outside Git."""

        root = _canonical_directory(workspace_root, "workspace root")
        if self.discover_git(root) is not None:
            raise InvalidScopePolicyError("Git directories require a repository project policy")
        repository_id = workspace_id_from_root(root, self._profile_namespace)
        return ScopePolicy(
            principal_id=self.principal_id,
            repository_id=repository_id,
            project_id=project_id_for_repository(repository_id, "."),
            project_root_rel=".",
            workspace_root=str(root),
            capture_allowed=capture_allowed,
            recall_allowed=recall_allowed,
            injection_allowed=injection_allowed,
            reflection_allowed=reflection_allowed,
            max_egress_policy=max_egress_policy,
            updated_at=updated_at,
        )

    def resolve(
        self,
        cwd: str | Path,
        policies: Iterable[ScopePolicy | Mapping[str, Any]],
    ) -> ResolvedScope:
        """Select the deepest containing configured root or fail closed."""

        cwd_path = _canonical_directory(cwd, "runtime cwd")
        git = self.discover_git(cwd_path)
        candidates: list[tuple[Path, ScopePolicy]] = []
        for raw_policy in policies:
            try:
                policy = (
                    raw_policy
                    if isinstance(raw_policy, ScopePolicy)
                    else ScopePolicy.from_mapping(raw_policy)
                )
            except (TypeError, ValueError) as exc:
                raise InvalidScopePolicyError("scope policy record is invalid") from exc
            if policy.principal_id != self.principal_id:
                raise InvalidScopePolicyError("scope policy principal does not match")
            if git is not None:
                if policy.is_workspace or policy.repository_id != git.repository_id:
                    continue
                root = _git_policy_root(git, policy)
            else:
                if not policy.is_workspace:
                    continue
                root = _workspace_policy_root(policy, self._profile_namespace)
            if cwd_path == root or cwd_path.is_relative_to(root):
                candidates.append((root, policy))
        root, policy = _select_most_specific(candidates)
        return ResolvedScope(
            principal_id=self.principal_id,
            repository_id=policy.repository_id,
            project_id=policy.project_id,
            project_root=root,
            policy=policy,
            repository_root=git.repository_root if git else None,
            git_common_dir=git.common_dir if git else None,
            workspace_root=root if policy.is_workspace else None,
        )


def _has_git_marker(cwd: Path) -> bool:
    return any((candidate / ".git").exists() for candidate in (cwd, *cwd.parents))


def _git_policy_root(git: GitContext, policy: ScopePolicy) -> Path:
    rel = normalize_project_root_rel(policy.project_root_rel)
    root = _canonical_directory(git.repository_root / rel, "configured project root")
    if not root.is_relative_to(git.repository_root):
        raise InvalidScopePolicyError("configured project root escaped the worktree")
    if policy.project_id != project_id_for_repository(policy.repository_id, rel):
        raise InvalidScopePolicyError("configured project identity is inconsistent")
    return root


def _workspace_policy_root(policy: ScopePolicy, profile_namespace: str | bytes) -> Path:
    root = _canonical_directory(policy.workspace_root or "", "configured workspace root")
    repository_id = workspace_id_from_root(root, profile_namespace)
    if policy.repository_id != repository_id or policy.project_id != project_id_for_repository(repository_id, "."):
        raise InvalidScopePolicyError("configured workspace identity is inconsistent")
    return root


def _select_most_specific(candidates: list[tuple[Path, ScopePolicy]]) -> tuple[Path, ScopePolicy]:
    if not candidates:
        raise ScopeNotConfiguredError("no configured project contains the runtime cwd")
    depth = max(len(root.parts) for root, _ in candidates)
    winners = [(root, policy) for root, policy in candidates if len(root.parts) == depth]
    unique = {(str(root), policy) for root, policy in winners}
    if len(unique) != 1:
        raise AmbiguousScopeError("multiple equally specific project policies match")
    return winners[0]
