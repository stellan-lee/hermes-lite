from __future__ import annotations

import json
import sys

import pytest

from model_tools import DEFAULT_TOOL_NAMES, ToolRuntime, handle_function_call
from tools import file_tools, registry


def execute(runtime, name, **arguments):
    return json.loads(runtime.execute(name, arguments))


def test_registry_is_fixed_and_schema_names_match():
    assert registry.names() == DEFAULT_TOOL_NAMES
    assert [item["function"]["name"] for item in registry.schemas()] == list(DEFAULT_TOOL_NAMES)


def test_write_read_patch_and_search(tmp_path):
    runtime = ToolRuntime(workspace=tmp_path, terminal_enabled=False)
    assert execute(runtime, "write_file", path="src/a.txt", content="Hello\nworld\n")["success"]
    duplicate = execute(runtime, "write_file", path="src/a.txt", content="no")
    assert duplicate == {
        "success": False,
        "error": "file already exists; set overwrite=true to replace it",
    }

    read = execute(runtime, "read_file", path="src/a.txt", start_line=2, end_line=2)
    assert read["content"] == "world\n"
    patched = execute(
        runtime,
        "patch",
        path="src/a.txt",
        old_text="world",
        new_text="Hermes",
    )
    assert patched["replacements"] == 1
    assert (tmp_path / "src/a.txt").read_text(encoding="utf-8") == "Hello\nHermes\n"

    found = execute(runtime, "search_files", path="src", query="hermes", glob="*.txt")
    assert found["results"] == [{"path": "src/a.txt", "line": 2, "text": "Hermes"}]
    listed = execute(runtime, "search_files", path="src", query="", glob="*.txt")
    assert listed["results"] == [{"path": "src/a.txt"}]


def test_patch_refuses_ambiguous_replacement(tmp_path):
    (tmp_path / "a.txt").write_text("same same", encoding="utf-8")
    runtime = ToolRuntime(workspace=tmp_path)
    result = execute(runtime, "patch", path="a.txt", old_text="same", new_text="new")
    assert result["success"] is False
    assert result["actual_replacements"] == 2


def test_integer_arguments_reject_booleans(tmp_path):
    (tmp_path / "a.txt").write_text("value", encoding="utf-8")
    runtime = ToolRuntime(workspace=tmp_path, terminal_enabled=False)
    assert execute(runtime, "read_file", path="a.txt", start_line=True)["success"] is False
    assert (
        execute(
            runtime,
            "patch",
            path="a.txt",
            old_text="value",
            new_text="new",
            expected_replacements=True,
        )["success"]
        is False
    )
    assert execute(runtime, "search_files", query="", max_results=True)["success"] is False


def test_paths_cannot_escape_workspace(tmp_path):
    runtime = ToolRuntime(workspace=tmp_path)
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    result = execute(runtime, "read_file", path=str(outside))
    assert result["success"] is False
    assert "escapes workspace" in result["error"]


def test_symlink_cannot_escape_workspace(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable")
    runtime = ToolRuntime(workspace=tmp_path)
    result = execute(runtime, "read_file", path="link.txt")
    assert result["success"] is False
    assert "escapes workspace" in result["error"]


def test_terminal_requires_enablement_and_approval(tmp_path):
    disabled = ToolRuntime(workspace=tmp_path, terminal_enabled=False)
    assert execute(disabled, "terminal", argv=[sys.executable, "-V"])["error"] == (
        "terminal execution is disabled"
    )

    no_callback = ToolRuntime(workspace=tmp_path, terminal_enabled=True)
    assert (
        "approval callback"
        in execute(no_callback, "terminal", argv=[sys.executable, "-V"])["error"]
    )

    denied = ToolRuntime(
        workspace=tmp_path,
        terminal_enabled=True,
        approval_callback=lambda _command: False,
    )
    assert execute(denied, "terminal", argv=[sys.executable, "-V"])["error"] == (
        "terminal command denied"
    )


def test_terminal_runs_without_shell_and_strips_secret_environment(tmp_path, monkeypatch):
    approvals: list[str] = []
    monkeypatch.setenv("SHOULD_NOT_LEAK_TOKEN", "secret")
    runtime = ToolRuntime(
        workspace=tmp_path,
        terminal_enabled=True,
        approval_callback=lambda command: approvals.append(command) or True,
    )
    result = execute(
        runtime,
        "terminal",
        argv=[
            sys.executable,
            "-c",
            "import os; print(os.getenv('SHOULD_NOT_LEAK_TOKEN', 'missing'))",
        ],
    )
    assert result["success"] is True
    assert result["exit_code"] == 0
    assert result["stdout"] == "missing\n"
    assert len(approvals) == 1


def test_terminal_escapes_approval_text_and_reports_nonzero_exit(tmp_path):
    approvals: list[str] = []
    runtime = ToolRuntime(
        workspace=tmp_path,
        terminal_enabled=True,
        approval_callback=lambda command: approvals.append(command) or True,
    )
    result = execute(
        runtime,
        "terminal",
        argv=[sys.executable, "-c", "raise SystemExit(3)", "\x1b[2J\nargument"],
    )
    assert result["success"] is False
    assert result["exit_code"] == 3
    assert result["error"] == "command exited with code 3"
    assert "\\u001b" in approvals[0]
    assert "\\nargument" in approvals[0]
    assert "\x1b" not in approvals[0]


def test_terminal_timeout_rejects_boolean(tmp_path):
    runtime = ToolRuntime(workspace=tmp_path, terminal_enabled=True, terminal_confirm=False)
    result = execute(runtime, "terminal", argv=[sys.executable, "-V"], timeout_seconds=True)
    assert result["success"] is False
    assert result["error"] == "timeout_seconds must be a positive integer"


def test_terminal_cwd_is_bounded(tmp_path):
    runtime = ToolRuntime(
        workspace=tmp_path,
        terminal_enabled=True,
        terminal_confirm=False,
    )
    result = execute(runtime, "terminal", argv=[sys.executable, "-V"], cwd=str(tmp_path.parent))
    assert result["success"] is False
    assert result["error"] == "cwd escapes workspace"


def test_dispatch_parses_json_and_respects_enabled_tools(tmp_path):
    runtime = ToolRuntime(workspace=tmp_path, enabled_tools=["search_files"])
    result = json.loads(handle_function_call("search_files", '{"query": ""}', runtime=runtime))
    assert result["success"] is True
    disabled = json.loads(handle_function_call("read_file", {"path": "a"}, runtime=runtime))
    assert disabled["error"] == "tool is disabled: read_file"
    invalid = json.loads(handle_function_call("search_files", "[]", runtime=runtime))
    assert invalid["error"] == "tool arguments must decode to an object"


def test_workspace_must_exist(tmp_path):
    with pytest.raises(ValueError, match="workspace is not a directory"):
        ToolRuntime(workspace=tmp_path / "missing")


def test_search_stops_walking_at_result_limit(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")

    def guarded_walk(_root, followlinks=False):
        assert followlinks is False
        yield str(tmp_path), [], ["a.txt"]
        raise AssertionError("search walked beyond the result limit")

    monkeypatch.setattr(file_tools.os, "walk", guarded_walk)
    runtime = ToolRuntime(workspace=tmp_path)
    result = execute(runtime, "search_files", query="", max_results=1)
    assert result == {"success": True, "results": [{"path": "a.txt"}], "truncated": True}
