"""Seed bundled skills without overwriting user customizations."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict

from agent.skill_utils import is_excluded_skill_path
from marlow_constants import get_bundled_skills_dir, get_marlow_home
from utils import atomic_replace

logger = logging.getLogger(__name__)

MARLOW_HOME = get_marlow_home()
SKILLS_DIR = MARLOW_HOME / "skills"
MANIFEST_FILE = SKILLS_DIR / ".bundled_manifest"
NO_BUNDLED_SKILLS_MARKER = ".no-bundled-skills"


def _get_bundled_dir() -> Path:
    return get_bundled_skills_dir(Path(__file__).parent.parent / "skills")


def _read_manifest() -> Dict[str, str]:
    if not MANIFEST_FILE.exists():
        return {}
    try:
        entries: Dict[str, str] = {}
        for raw in MANIFEST_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            name, separator, digest = line.partition(":")
            entries[name.strip()] = digest.strip() if separator else ""
        return entries
    except OSError:
        return {}


def _write_manifest(entries: Dict[str, str]) -> None:
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(f"{name}:{digest}\n" for name, digest in sorted(entries.items()))
    fd, temp_path = tempfile.mkstemp(
        dir=str(MANIFEST_FILE.parent), prefix=".bundled_manifest_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        atomic_replace(temp_path, MANIFEST_FILE)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _read_skill_name(skill_md: Path) -> str:
    fallback = skill_md.parent.name
    try:
        content = skill_md.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return fallback
    in_frontmatter = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter and stripped.startswith("name:"):
            value = stripped.partition(":")[2].strip().strip("\"'")
            return value or fallback
    return fallback


def _discover_bundled_skills(root: Path) -> list[tuple[str, Path]]:
    if not root.exists():
        return []
    return [
        (_read_skill_name(skill_md), skill_md.parent)
        for skill_md in sorted(root.rglob("SKILL.md"))
        if not is_excluded_skill_path(skill_md)
    ]


def _dir_hash(directory: Path) -> str:
    digest = hashlib.md5()
    try:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
                digest.update(path.read_bytes())
    except OSError:
        pass
    return digest.hexdigest()


def _read_suppressed_names() -> set[str]:
    try:
        from tools.skill_usage import read_suppressed_names

        return set(read_suppressed_names())
    except Exception:
        return set()


def sync_skills(quiet: bool = False) -> dict:
    """Copy new or unmodified bundled skills into the active profile."""
    empty = {
        "copied": [],
        "updated": [],
        "skipped": 0,
        "user_modified": [],
        "cleaned": [],
        "suppressed": [],
        "total_bundled": 0,
    }
    if (MARLOW_HOME / NO_BUNDLED_SKILLS_MARKER).exists():
        return {**empty, "skipped_opt_out": True}

    bundled_dir = _get_bundled_dir()
    skills = _discover_bundled_skills(bundled_dir)
    if not skills:
        return empty

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = _read_manifest()
    suppressed = _read_suppressed_names()
    copied: list[str] = []
    updated: list[str] = []
    modified: list[str] = []
    suppressed_names: list[str] = []
    skipped = 0

    for name, source in skills:
        if name in suppressed:
            suppressed_names.append(name)
            continue
        destination = SKILLS_DIR / source.relative_to(bundled_dir)
        source_hash = _dir_hash(source)
        origin_hash = manifest.get(name)

        if origin_hash is None:
            if destination.exists():
                if _dir_hash(destination) == source_hash:
                    manifest[name] = source_hash
                else:
                    modified.append(name)
                skipped += 1
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination)
            manifest[name] = source_hash
            copied.append(name)
            if not quiet:
                print(f"  + {name}")
            continue

        if not destination.exists():
            skipped += 1
            continue
        destination_hash = _dir_hash(destination)
        if origin_hash and destination_hash != origin_hash:
            modified.append(name)
            skipped += 1
            continue
        if destination_hash == source_hash:
            manifest[name] = source_hash
            skipped += 1
            continue

        backup = destination.with_suffix(".bak")
        if backup.exists():
            shutil.rmtree(backup)
        shutil.move(str(destination), str(backup))
        try:
            shutil.copytree(source, destination)
        except Exception:
            if destination.exists():
                shutil.rmtree(destination)
            shutil.move(str(backup), str(destination))
            raise
        shutil.rmtree(backup)
        manifest[name] = source_hash
        updated.append(name)
        if not quiet:
            print(f"  ↑ {name}")

    bundled_names = {name for name, _source in skills}
    cleaned = sorted(set(manifest) - bundled_names)
    for name in cleaned:
        manifest.pop(name, None)

    for description in bundled_dir.rglob("DESCRIPTION.md"):
        destination = SKILLS_DIR / description.relative_to(bundled_dir)
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(description, destination)

    _write_manifest(manifest)
    return {
        "copied": copied,
        "updated": updated,
        "skipped": skipped,
        "user_modified": modified,
        "cleaned": cleaned,
        "suppressed": suppressed_names,
        "total_bundled": len(skills),
    }
