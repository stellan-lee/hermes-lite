from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from agent.experience.scope import (
    AmbiguousScopeError,
    ScopeNotConfiguredError,
    ScopeResolutionError,
    ScopeResolver,
    normalize_project_root_rel,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init")
    return path


def test_most_specific_explicit_project_policy_wins(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    api = repo / "apps" / "api"
    api_src = api / "src"
    web = repo / "apps" / "web"
    api_src.mkdir(parents=True)
    web.mkdir(parents=True)
    resolver = ScopeResolver("profile-a")
    repo_policy = resolver.make_git_policy(
        repo, ".", recall_allowed=True, injection_allowed=True
    )
    api_policy = resolver.make_git_policy(
        repo, "apps/api", recall_allowed=True, injection_allowed=True
    )
    web_policy = resolver.make_git_policy(
        repo, "apps/web", recall_allowed=True, injection_allowed=True
    )

    resolved = resolver.resolve(api_src, [repo_policy, web_policy, api_policy])

    assert resolved.project_id == api_policy.project_id
    assert resolved.project_root == api.resolve()
    assert resolved.as_ref().repository_id == repo_policy.repository_id


def test_repo_root_does_not_imply_repo_wide_project_grant(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "apps" / "api").mkdir(parents=True)
    (repo / "apps" / "web").mkdir(parents=True)
    resolver = ScopeResolver("profile-a")
    policies = [
        resolver.make_git_policy(
            repo, "apps/api", recall_allowed=True, injection_allowed=True
        ),
        resolver.make_git_policy(
            repo, "apps/web", recall_allowed=True, injection_allowed=True
        ),
    ]

    with pytest.raises(ScopeNotConfiguredError):
        resolver.resolve(repo, policies)


def test_tied_policy_records_fail_closed(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    project = repo / "project"
    project.mkdir()
    resolver = ScopeResolver("profile-a")
    policy = resolver.make_git_policy(repo, "project")
    conflicting = replace(policy, recall_allowed=True, injection_allowed=True)

    with pytest.raises(AmbiguousScopeError):
        resolver.resolve(project, [policy, conflicting])


def test_git_common_directory_identity_is_shared_by_sibling_worktrees(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Hermes Test")
    _git(repo, "commit", "--allow-empty", "-m", "initial")
    sibling = tmp_path / "sibling"
    _git(repo, "worktree", "add", "-b", "sibling", str(sibling))
    resolver = ScopeResolver("profile-a")

    primary = resolver.discover_git(repo)
    secondary = resolver.discover_git(sibling)

    assert primary is not None and secondary is not None
    assert primary.common_dir == secondary.common_dir
    assert primary.repository_id == secondary.repository_id


def test_git_discovery_ignores_repository_shaping_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_a = _init_repo(tmp_path / "repo-a")
    repo_b = _init_repo(tmp_path / "repo-b")
    monkeypatch.setenv("GIT_DIR", str(repo_a / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(repo_a))
    resolver = ScopeResolver("profile-a")

    discovered = resolver.discover_git(repo_b)

    assert discovered is not None
    assert discovered.repository_root == repo_b.resolve()


def test_non_git_workspace_requires_explicit_root_and_move_is_new_scope(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    child = root / "src"
    child.mkdir(parents=True)
    resolver = ScopeResolver("profile-a")

    with pytest.raises(ScopeNotConfiguredError):
        resolver.resolve(child, [])

    policy = resolver.make_workspace_policy(
        root, recall_allowed=True, injection_allowed=True
    )
    assert policy.recall_allowed is True
    assert resolver.resolve(child, [policy]).workspace_root == root.resolve()

    moved = tmp_path / "moved"
    root.rename(moved)
    with pytest.raises(ScopeResolutionError):
        resolver.resolve(moved / "src", [policy])


@pytest.mark.parametrize("value", ["../escape", "/absolute", "a\\b", ""])
def test_project_roots_must_be_safe_repo_relative_paths(value: str) -> None:
    with pytest.raises(ScopeResolutionError):
        normalize_project_root_rel(value)
