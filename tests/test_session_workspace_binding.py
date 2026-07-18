"""Session workspace grouping contracts."""

from marlow_state import workspace_key


def test_workspace_key_prefers_repo_root():
    assert workspace_key({"git_repo_root": "/www/app", "cwd": "/www/app/src"}) == "/www/app"


def test_workspace_key_falls_back_to_cwd():
    assert workspace_key({"cwd": "/work/notes"}) == "/work/notes"
    assert workspace_key({}) is None


def test_workspace_key_ignores_branch():
    assert workspace_key({"git_repo_root": "/www/app", "git_branch": "one"}) == workspace_key(
        {"git_repo_root": "/www/app", "git_branch": "two"}
    )
