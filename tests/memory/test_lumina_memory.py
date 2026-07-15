"""Tests for Lumina durable memory mutations."""

from pathlib import Path

from secretary.memory.lumina_memory import LuminaMemory


def test_mutate_memory_add_to_memory_md(tmp_path: Path) -> None:
    memory = LuminaMemory(tmp_path)
    result = memory.mutate_memory("add", "memory", text="Prefer concise replies")
    assert "added" in result.lower() or "已" in result
    assert "Prefer concise replies" in memory.read_memory_md()


def test_mutate_memory_replace_substring(tmp_path: Path) -> None:
    memory = LuminaMemory(tmp_path)
    memory.write_memory_md("Use Python 3.11")
    result = memory.mutate_memory(
        "replace", "memory", old_text="3.11", text="3.12"
    )
    assert "3.11" not in memory.read_memory_md()
    assert "3.12" in memory.read_memory_md()
    assert result


def test_mutate_memory_remove_substring(tmp_path: Path) -> None:
    memory = LuminaMemory(tmp_path)
    memory.write_user_md("Name: Alex\nDislikes: emoji")
    result = memory.mutate_memory("remove", "user", old_text="Dislikes: emoji")
    content = memory.read_user_md()
    assert "Dislikes" not in content
    assert "Alex" in content
    assert result


def test_mutate_memory_rejects_unknown_action(tmp_path: Path) -> None:
    memory = LuminaMemory(tmp_path)
    try:
        memory.mutate_memory("purge", "memory", text="x")
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_import_from_hermes_top_level(tmp_path: Path, monkeypatch) -> None:
    """Import MEMORY.md/USER.md from ~/.hermes/ top-level into Lumina."""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "MEMORY.md").write_text("# Env\n- macOS\n", encoding="utf-8")
    (hermes_home / "USER.md").write_text("# User\n- prefers concise\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    memory = LuminaMemory(tmp_path / "lumina")
    imported = memory.import_from_hermes()

    assert set(imported.keys()) == {"memory_md", "user_md"}
    assert "- macOS" in memory.read_memory_md()
    assert "prefers concise" in memory.read_user_md()


def test_import_from_hermes_nested_memories_dir(tmp_path: Path, monkeypatch) -> None:
    """Import from ~/.hermes/memories/ when top-level files missing."""
    hermes_home = tmp_path / ".hermes"
    (hermes_home / "memories").mkdir(parents=True)
    (hermes_home / "memories" / "MEMORY.md").write_text("# Nested\n- fact\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    memory = LuminaMemory(tmp_path / "lumina")
    imported = memory.import_from_hermes()

    assert "memory_md" in imported
    assert "user_md" not in imported
    assert "- fact" in memory.read_memory_md()


def test_import_from_hermes_no_files(tmp_path: Path, monkeypatch) -> None:
    """Return empty dict when no Hermes files exist."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    memory = LuminaMemory(tmp_path / "lumina")
    assert memory.import_from_hermes() == {}


def test_episodes_table_has_reflection_columns(tmp_path: Path) -> None:
    """F21: episodes table must have failure_mode, reflection_text, thread_id columns."""
    mem = LuminaMemory(tmp_path)
    with mem._connect_session() as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(episodes)")}
    assert "failure_mode" in cols
    assert "reflection_text" in cols
    assert "thread_id" in cols


def test_episodes_fts_indexes_reflection_text(tmp_path: Path) -> None:
    """F21: episodes_fts must index reflection_text for keyword search."""
    mem = LuminaMemory(tmp_path)
    with mem._connect_session() as conn:
        fts_cols = {row["name"] for row in conn.execute("PRAGMA table_info(episodes_fts)")}
    assert "reflection_text" in fts_cols
    assert "failure_mode" in fts_cols
