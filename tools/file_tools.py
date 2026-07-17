"""Workspace-contained file tools."""

from __future__ import annotations

import fnmatch
import os
import stat
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from tools.registry import (
    ToolContext,
    ToolDefinition,
    error_result,
    registry,
    success_result,
)

_MAX_READ_CHARS = 100_000
_MAX_SEARCH_FILE_BYTES = 1_000_000
_SKIP_DIRECTORIES = {".git", ".venv", "venv", "node_modules", "__pycache__"}


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _bounded_path(
    context: ToolContext,
    raw_path: str,
    *,
    must_exist: bool = False,
) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("path must be a non-empty string")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = context.workspace / candidate
    candidate = candidate.resolve(strict=False)
    try:
        candidate.relative_to(context.workspace)
    except ValueError as exc:
        raise ValueError(f"path escapes workspace: {raw_path}") from exc
    if must_exist and not candidate.exists():
        raise ValueError(f"path does not exist: {raw_path}")
    return candidate


def _relative(context: ToolContext, path: Path) -> str:
    return str(path.relative_to(context.workspace)) or "."


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"not a regular file: {path.name}")
    return path.read_text(encoding="utf-8", errors="replace")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    previous_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temp_name = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temp_name, previous_mode)
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def _read_file(arguments: Mapping[str, Any], context: ToolContext) -> str:
    path = _bounded_path(context, arguments.get("path", ""), must_exist=True)
    text = _read_text(path)
    lines = text.splitlines(keepends=True)

    start_line = arguments.get("start_line", 1)
    end_line = arguments.get("end_line", len(lines) or 1)
    if not _is_integer(start_line) or start_line < 1:
        return error_result("start_line must be a positive integer")
    if not _is_integer(end_line) or end_line < start_line:
        return error_result("end_line must be an integer greater than or equal to start_line")

    selected = "".join(lines[start_line - 1 : end_line])
    truncated = len(selected) > _MAX_READ_CHARS
    if truncated:
        selected = selected[:_MAX_READ_CHARS]
    return success_result(
        path=_relative(context, path),
        content=selected,
        start_line=start_line,
        end_line=min(end_line, len(lines)),
        truncated=truncated,
    )


def _write_file(arguments: Mapping[str, Any], context: ToolContext) -> str:
    path = _bounded_path(context, arguments.get("path", ""))
    content = arguments.get("content")
    overwrite = arguments.get("overwrite", False)
    if not isinstance(content, str):
        return error_result("content must be a string")
    if not isinstance(overwrite, bool):
        return error_result("overwrite must be a boolean")
    if path.exists() and not overwrite:
        return error_result("file already exists; set overwrite=true to replace it")
    if path.exists() and not path.is_file():
        return error_result("path exists and is not a regular file")
    _atomic_write(path, content)
    return success_result(path=_relative(context, path), bytes=len(content.encode("utf-8")))


def _patch_file(arguments: Mapping[str, Any], context: ToolContext) -> str:
    path = _bounded_path(context, arguments.get("path", ""), must_exist=True)
    old_text = arguments.get("old_text")
    new_text = arguments.get("new_text")
    expected = arguments.get("expected_replacements", 1)
    if not isinstance(old_text, str) or not old_text:
        return error_result("old_text must be a non-empty string")
    if not isinstance(new_text, str):
        return error_result("new_text must be a string")
    if not _is_integer(expected) or expected < 1:
        return error_result("expected_replacements must be a positive integer")

    content = _read_text(path)
    actual = content.count(old_text)
    if actual != expected:
        return error_result(
            "replacement count mismatch",
            expected_replacements=expected,
            actual_replacements=actual,
        )
    _atomic_write(path, content.replace(old_text, new_text, expected))
    return success_result(path=_relative(context, path), replacements=expected)


def _iter_search_files(root: Path, pattern: str) -> Iterator[Path]:
    if root.is_file():
        yield root
        return

    for current_root, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names[:] = [
            name
            for name in directory_names
            if name not in _SKIP_DIRECTORIES and not (Path(current_root) / name).is_symlink()
        ]
        current = Path(current_root)
        for file_name in file_names:
            path = current / file_name
            relative = str(path.relative_to(root))
            if fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(file_name, pattern):
                yield path


def _search_files(arguments: Mapping[str, Any], context: ToolContext) -> str:
    root = _bounded_path(context, arguments.get("path", "."), must_exist=True)
    query = arguments.get("query", "")
    pattern = arguments.get("glob", "*")
    case_sensitive = arguments.get("case_sensitive", False)
    max_results = arguments.get("max_results", 50)
    if not isinstance(query, str) or not isinstance(pattern, str):
        return error_result("query and glob must be strings")
    if not isinstance(case_sensitive, bool):
        return error_result("case_sensitive must be a boolean")
    if not _is_integer(max_results) or not 1 <= max_results <= 500:
        return error_result("max_results must be between 1 and 500")

    needle = query if case_sensitive else query.casefold()
    results: list[dict[str, Any]] = []
    for path in _iter_search_files(root, pattern):
        if len(results) >= max_results:
            break
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(context.workspace)
        except ValueError:
            continue
        if resolved.is_symlink() or not resolved.is_file():
            continue
        try:
            if resolved.stat().st_size > _MAX_SEARCH_FILE_BYTES:
                continue
        except OSError:
            continue

        if not query:
            results.append({"path": _relative(context, resolved)})
            if len(results) >= max_results:
                return success_result(results=results, truncated=True)
            continue
        try:
            with resolved.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, 1):
                    haystack = line if case_sensitive else line.casefold()
                    if needle in haystack:
                        results.append(
                            {
                                "path": _relative(context, resolved),
                                "line": line_number,
                                "text": line.rstrip("\n")[:500],
                            }
                        )
                        if len(results) >= max_results:
                            break
        except OSError:
            continue
        if len(results) >= max_results:
            return success_result(results=results, truncated=True)

    return success_result(results=results, truncated=False)


_OBJECT_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False}

registry.register(
    ToolDefinition(
        name="read_file",
        description="Read a UTF-8 text file inside the workspace.",
        parameters={
            **_OBJECT_SCHEMA,
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
        },
        handler=_read_file,
    )
)

registry.register(
    ToolDefinition(
        name="write_file",
        description="Create or replace a UTF-8 text file inside the workspace.",
        parameters={
            **_OBJECT_SCHEMA,
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "overwrite": {"type": "boolean", "default": False},
            },
            "required": ["path", "content"],
        },
        handler=_write_file,
    )
)

registry.register(
    ToolDefinition(
        name="patch",
        description="Replace an exact text fragment in one workspace file.",
        parameters={
            **_OBJECT_SCHEMA,
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string", "minLength": 1},
                "new_text": {"type": "string"},
                "expected_replacements": {"type": "integer", "minimum": 1, "default": 1},
            },
            "required": ["path", "old_text", "new_text"],
        },
        handler=_patch_file,
    )
)

registry.register(
    ToolDefinition(
        name="search_files",
        description="List files or search their text inside the workspace.",
        parameters={
            **_OBJECT_SCHEMA,
            "properties": {
                "query": {"type": "string", "default": ""},
                "path": {"type": "string", "default": "."},
                "glob": {"type": "string", "default": "*"},
                "case_sensitive": {"type": "boolean", "default": False},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
            },
        },
        handler=_search_files,
    )
)
