"""Behavior contracts for journey node edit/delete (agent.learning_mutations).

Exercises the real on-disk resolution (skills dir + MEMORY.md/USER.md chunking)
against a temp HERMES_HOME, never mocks — the id→file mapping is the whole point.
"""

from __future__ import annotations

import importlib
import multiprocessing
import os
import time
import pytest
import threading

from agent import learning_mutations as lm
from hermes_constants import get_hermes_home

_SKILL = """---
name: my-skill
description: A test skill.
---

# My Skill

Body.
"""


def _edit_memory_process(home: str, node_id: str, value: str, barrier, results) -> None:
    """Spawn-safe worker that widens the read/write race around each edit."""
    os.environ["HERMES_HOME"] = home
    import hermes_constants
    from agent import learning_mutations

    importlib.reload(hermes_constants)
    mutations = importlib.reload(learning_mutations)
    original_write = mutations._write_chunks

    def delayed_write(path, chunks):
        time.sleep(0.15)
        original_write(path, chunks)

    mutations._write_chunks = delayed_write
    barrier.wait(timeout=10)
    results.put(mutations.edit_node(node_id, value))


@pytest.fixture
def home():
    base = get_hermes_home()
    (base / "memories").mkdir(parents=True, exist_ok=True)
    (base / "memories" / "MEMORY.md").write_text("alpha note\nline two\n§\nbeta note", encoding="utf-8")
    (base / "memories" / "USER.md").write_text("user profile note", encoding="utf-8")
    skill = base / "skills" / "my-skill"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(_SKILL, encoding="utf-8")
    return base


def _ids_by_content():
    from agent.learning_graph import _memory_cards

    return {card["body"]: card["id"] for card in _memory_cards()}


def test_parse_node_kind():
    assert lm.parse_node_kind("memory:memory:0123456789abcdef") == "memory"
    assert lm.parse_node_kind("memory:profile:fedcba9876543210") == "memory"
    assert lm.parse_node_kind("debugging-hermes") == "skill"


def test_memory_content_ids_map_across_files(home):
    ids = _ids_by_content()
    assert lm.node_detail(ids["alpha note\nline two"])["content"].startswith("alpha note")
    assert lm.node_detail(ids["beta note"])["content"] == "beta note"
    assert lm.node_detail(ids["user profile note"])["content"] == "user profile note"


def test_memory_label_is_first_line(home):
    assert lm.node_detail(_ids_by_content()["alpha note\nline two"])["label"] == "alpha note"


def test_delete_memory_rewrites_file(home):
    assert lm.delete_node(_ids_by_content()["alpha note\nline two"])["ok"]
    remaining = (home / "memories" / "MEMORY.md").read_text(encoding="utf-8")
    assert "alpha note" not in remaining
    assert "beta note" in remaining


def test_edit_memory_replaces_chunk(home):
    assert lm.edit_node(_ids_by_content()["user profile note"], "rewritten profile")["ok"]
    assert (home / "memories" / "USER.md").read_text(encoding="utf-8").strip() == "rewritten profile"


def test_edit_memory_empty_is_rejected(home):
    res = lm.edit_node(_ids_by_content()["beta note"], "   ")
    assert not res["ok"]
    assert "delete" in res["message"]


def test_stale_memory_index_errors(home):
    res = lm.node_detail("memory:memory:0000000000000000")
    assert not res["ok"]


def test_memory_id_remains_bound_after_earlier_card_is_deleted(home):
    ids = _ids_by_content()
    beta_id = ids["beta note"]
    assert lm.delete_node(ids["alpha note\nline two"])["ok"]
    assert lm.edit_node(beta_id, "beta rewritten")["ok"]
    text = (home / "memories" / "MEMORY.md").read_text(encoding="utf-8")
    assert "beta rewritten" in text


def test_concurrent_mutations_allow_only_one_claim_of_same_card(home):
    node_id = _ids_by_content()["beta note"]
    barrier = threading.Barrier(2)
    results = []

    def edit(value):
        barrier.wait(timeout=5)
        results.append(lm.edit_node(node_id, value))

    threads = [threading.Thread(target=edit, args=(f"value {i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert sum(1 for result in results if result["ok"]) == 1
    assert sum(1 for result in results if "stale" in result.get("message", "")) == 1


def test_cross_process_edits_of_distinct_cards_do_not_lose_updates(home):
    ids = _ids_by_content()
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    results = ctx.Queue()
    edits = [
        (ids["alpha note\nline two"], "alpha rewritten"),
        (ids["beta note"], "beta rewritten"),
    ]
    processes = [
        ctx.Process(
            target=_edit_memory_process,
            args=(str(home), node_id, value, barrier, results),
        )
        for node_id, value in edits
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    outcomes = [results.get(timeout=2) for _ in processes]
    assert all(result["ok"] for result in outcomes)
    text = (home / "memories" / "MEMORY.md").read_text(encoding="utf-8")
    assert "alpha rewritten" in text
    assert "beta rewritten" in text


def test_bad_memory_id_returns_error(home):
    res = lm.delete_node("memory:bogus:0")
    assert not res["ok"]


def test_skill_detail_returns_skill_md(home):
    d = lm.node_detail("my-skill")
    assert d["ok"] and d["kind"] == "skill"
    assert "name: my-skill" in d["content"]


def test_delete_skill_archives_recoverably(home):
    res = lm.delete_node("my-skill")
    assert res["ok"]
    assert not (home / "skills" / "my-skill").exists()
    assert (home / "skills" / ".archive" / "my-skill" / "SKILL.md").exists()


def test_delete_pinned_skill_refused(home):
    from tools import skill_usage

    skill_usage.set_pinned("my-skill", True)
    res = lm.delete_node("my-skill")
    assert not res["ok"]
    assert "pinned" in res["message"]
    assert (home / "skills" / "my-skill").exists()


def test_edit_skill_rewrites_and_validates(home):
    bad = lm.edit_node("my-skill", "no frontmatter here")
    assert not bad["ok"]
    good = lm.edit_node("my-skill", _SKILL.replace("A test skill.", "Updated desc."))
    assert good["ok"]
    assert "Updated desc." in (home / "skills" / "my-skill" / "SKILL.md").read_text(encoding="utf-8")


def test_missing_skill_detail(home):
    assert not lm.node_detail("nonexistent-skill")["ok"]
