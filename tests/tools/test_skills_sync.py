"""Tests for local bundled-skill synchronization."""

from unittest.mock import patch

from tools.skills_sync import _read_manifest, _write_manifest, _read_skill_name


def test_manifest_roundtrip(tmp_path):
    manifest = tmp_path / ".bundled_manifest"
    with patch("tools.skills_sync.MANIFEST_FILE", manifest):
        _write_manifest({"zeta": "two", "alpha": "one"})
        assert _read_manifest() == {"alpha": "one", "zeta": "two"}


def test_read_skill_name_from_frontmatter(tmp_path):
    skill_dir = tmp_path / "folder-name"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("---\nname: declared-name\n---\n", encoding="utf-8")
    assert _read_skill_name(skill_md) == "declared-name"
