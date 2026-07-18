"""User-initiated edit/delete for journey nodes (learned skills + memories).

The journey graph (``agent.learning_graph``) gives every node a stable id:

- **skills** → the skill name (e.g. ``"debugging-marlow-desktop"``)
- **memories** → ``memory:<source>:<content-hash>`` where ``source`` is
  ``memory`` (``MEMORY.md``) or ``profile`` (``USER.md``). The hash keeps an
  id bound to its content when other cards are inserted or removed.

This module maps a node id back to its on-disk home and performs the mutation,
shared by the CLI (``marlow journey delete|edit``), the TUI ``/journey`` overlay
(gateway RPCs), and the desktop GUI (REST). Deleting a skill *archives* it
(recoverable via ``marlow curator restore``); deleting a memory rewrites its
file. Pure stdlib + existing skill/memory helpers.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from utils import atomic_replace, interprocess_file_lock

_MEMORY_DELIM = "\n§\n"
_MEMORY_FILES = {"memory": "MEMORY.md", "profile": "USER.md"}
_mutation_lock = threading.RLock()


def _journey_file_lock():
    return interprocess_file_lock(_memories_dir() / ".journey.lock")


def parse_node_kind(node_id: str) -> str:
    return "memory" if node_id.startswith("memory:") else "skill"


def _memories_dir() -> Path:
    from marlow_constants import get_marlow_home

    return get_marlow_home() / "memories"


def _parse_memory_id(node_id: str) -> tuple[str, str]:
    """``memory:<source>:<content-hash>`` → (source, content_hash)."""
    parts = node_id.split(":", 2)
    if len(parts) != 3 or parts[0] != "memory" or parts[1] not in _MEMORY_FILES:
        raise ValueError(f"bad memory node id: {node_id!r}")
    fingerprint = parts[2].lower()
    if len(fingerprint) != 16 or any(c not in "0123456789abcdef" for c in fingerprint):
        raise ValueError(f"bad memory node id: {node_id!r}")
    return parts[1], fingerprint


def _chunk_fingerprint(chunk: str) -> str:
    return hashlib.sha256(chunk.strip().encode("utf-8")).hexdigest()[:16]


def _read_chunks(path: Path) -> list[str]:
    """Raw ``§``-delimited chunks, preserving formatting; empties dropped to
    match ``_memory_cards`` indexing."""
    text = path.read_text(encoding="utf-8")

    return [c for c in text.split(_MEMORY_DELIM) if c.strip()]


def _locate_memory(source: str, fingerprint: str) -> tuple[Path, list[str], int]:
    """Resolve a memory card to its file, all chunks, and local index."""
    path = _memories_dir() / _MEMORY_FILES[source]
    if not path.exists():
        raise ValueError(f"{path.name} not found")
    chunks = _read_chunks(path)
    matches = [
        i
        for i, chunk in enumerate(chunks)
        if _chunk_fingerprint(chunk) == fingerprint
    ]
    if not matches:
        raise ValueError("memory node id is stale — refresh the graph")
    if len(matches) > 1:
        raise ValueError("memory node id is ambiguous — duplicate card content")
    return path, chunks, matches[0]


# ── Inspect (edit prefill) ──────────────────────────────────────────────────


def node_detail(node_id: str) -> dict[str, Any]:
    """Current content for an edit prefill. ``content`` is the full SKILL.md
    (skills) or the raw memory chunk (memories)."""
    try:
        with _mutation_lock:
            return _node_detail(node_id)
    except (ValueError, IndexError) as exc:
        return {"ok": False, "message": str(exc)}


def _node_detail(node_id: str) -> dict[str, Any]:
    if parse_node_kind(node_id) == "memory":
        source, fingerprint = _parse_memory_id(node_id)
        _, chunks, local = _locate_memory(source, fingerprint)
        body = chunks[local].strip()

        return {"ok": True, "kind": "memory", "id": node_id, "label": body.splitlines()[0][:80], "content": body}

    from tools.skill_manager_tool import _find_skill

    found = _find_skill(node_id)
    if not found:
        return {"ok": False, "message": f"skill '{node_id}' not found"}
    skill_md = Path(found["path"]) / "SKILL.md"
    if not skill_md.exists():
        return {"ok": False, "message": f"SKILL.md missing for '{node_id}'"}

    return {
        "ok": True,
        "kind": "skill",
        "id": node_id,
        "label": node_id,
        "content": skill_md.read_text(encoding="utf-8"),
    }


# ── Delete ──────────────────────────────────────────────────────────────────


def delete_node(node_id: str) -> dict[str, Any]:
    try:
        with _mutation_lock, _journey_file_lock():
            return _delete_memory(node_id) if parse_node_kind(node_id) == "memory" else _delete_skill(node_id)
    except (ValueError, IndexError) as exc:
        return {"ok": False, "message": str(exc)}


def _delete_skill(name: str) -> dict[str, Any]:
    from tools import skill_usage

    if skill_usage.get_record(name).get("pinned"):
        return {"ok": False, "message": f"'{name}' is pinned — unpin it first (marlow curator unpin {name})"}

    ok, message = skill_usage.archive_skill(name)
    if ok:
        _clear_skill_cache()

    return {
        "ok": ok,
        "message": (
            f"archived '{name}' — restore with: marlow curator restore {name}"
            if ok
            else message
        ),
    }


def _delete_memory(node_id: str) -> dict[str, Any]:
    source, fingerprint = _parse_memory_id(node_id)
    path, chunks, local = _locate_memory(source, fingerprint)

    del chunks[local]
    _write_chunks(path, chunks)

    return {"ok": True, "message": f"deleted memory from {path.name}"}


# ── Edit ────────────────────────────────────────────────────────────────────


def edit_node(node_id: str, content: str) -> dict[str, Any]:
    try:
        with _mutation_lock, _journey_file_lock():
            if parse_node_kind(node_id) == "memory":
                return _edit_memory(node_id, content)
            return _edit_skill(node_id, content)
    except (ValueError, IndexError) as exc:
        return {"ok": False, "message": str(exc)}


def _edit_skill(name: str, content: str) -> dict[str, Any]:
    from tools.skill_manager_tool import _edit_skill as _do_edit

    result = _do_edit(name, content)
    if result.get("success"):
        _clear_skill_cache()

        return {"ok": True, "message": f"updated '{name}'"}

    return {"ok": False, "message": result.get("error", "edit failed")}


def _edit_memory(node_id: str, content: str) -> dict[str, Any]:
    source, fingerprint = _parse_memory_id(node_id)
    body = content.strip()
    if not body:
        return {"ok": False, "message": "empty memory — use delete to remove it"}
    path, chunks, local = _locate_memory(source, fingerprint)

    chunks[local] = body
    _write_chunks(path, chunks)

    return {"ok": True, "message": f"updated memory in {path.name}"}


# ── Helpers ─────────────────────────────────────────────────────────────────


def _write_chunks(path: Path, chunks: list[str]) -> None:
    body = _MEMORY_DELIM.join(c.strip() for c in chunks)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{body}\n" if body else "")
            handle.flush()
            os.fsync(handle.fileno())
        atomic_replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _clear_skill_cache() -> None:
    try:
        from agent.prompt_builder import clear_skills_system_prompt_cache

        clear_skills_system_prompt_cache(clear_snapshot=True)
    except Exception:
        pass
