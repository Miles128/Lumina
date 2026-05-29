"""Tests for Hermes durable memory mutations."""

from pathlib import Path

from secretary.memory.hermes_memory import HermesMemory


def test_mutate_memory_add_to_memory_md(tmp_path: Path) -> None:
    hermes = HermesMemory(tmp_path)
    result = hermes.mutate_memory("add", "memory", text="Prefer concise replies")
    assert "added" in result.lower() or "已" in result
    assert "Prefer concise replies" in hermes.read_memory_md()


def test_mutate_memory_replace_substring(tmp_path: Path) -> None:
    hermes = HermesMemory(tmp_path)
    hermes.write_memory_md("Use Python 3.11")
    result = hermes.mutate_memory(
        "replace", "memory", old_text="3.11", text="3.12"
    )
    assert "3.11" not in hermes.read_memory_md()
    assert "3.12" in hermes.read_memory_md()
    assert result


def test_mutate_memory_remove_substring(tmp_path: Path) -> None:
    hermes = HermesMemory(tmp_path)
    hermes.write_user_md("Name: Alex\nDislikes: emoji")
    result = hermes.mutate_memory("remove", "user", old_text="Dislikes: emoji")
    content = hermes.read_user_md()
    assert "Dislikes" not in content
    assert "Alex" in content
    assert result


def test_mutate_memory_rejects_unknown_action(tmp_path: Path) -> None:
    hermes = HermesMemory(tmp_path)
    try:
        hermes.mutate_memory("purge", "memory", text="x")
        raised = False
    except ValueError:
        raised = True
    assert raised
