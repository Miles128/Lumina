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


def test_mutate_memory_rejects_retired_user_target(tmp_path: Path) -> None:
    """USER.md 已退役：target=user 应抛 ValueError，引导调用方改用 ProfileService。"""
    memory = LuminaMemory(tmp_path)
    try:
        memory.mutate_memory("add", "user", text="Name: Alex")
        raised = False
    except ValueError as exc:
        raised = True
        assert "user" in str(exc).lower()
    assert raised


def test_mutate_memory_remove_substring(tmp_path: Path) -> None:
    """replace/remove 仍对 memory target 正常工作。"""
    memory = LuminaMemory(tmp_path)
    memory.write_memory_md("Name: Alex\nDislikes: emoji")
    result = memory.mutate_memory(
        "remove", "memory", old_text="Dislikes: emoji"
    )
    content = memory.read_memory_md()
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
    """Import MEMORY.md from ~/.hermes/ top-level into Lumina. USER.md 不再导入。"""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "MEMORY.md").write_text("# Env\n- macOS\n", encoding="utf-8")
    (hermes_home / "USER.md").write_text("# User\n- prefers concise\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    memory = LuminaMemory(tmp_path / "lumina")
    imported = memory.import_from_hermes()

    assert imported == {"memory_md": str(hermes_home / "MEMORY.md")}
    assert "- macOS" in memory.read_memory_md()
    # USER.md 不应被导入
    assert not (tmp_path / "lumina" / "memories" / "USER.md").exists()


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


def test_prompt_snapshot_only_returns_memory_md(tmp_path: Path) -> None:
    """USER.md 退役后，prompt_snapshot 只返回 ## Durable Memory 段。"""
    memory = LuminaMemory(tmp_path)
    memory.write_memory_md("- env fact: macOS")
    # 即便旧 USER.md 文件残留，也不应被读取
    (tmp_path / "memories" / "USER.md").write_text("- stale user fact\n", encoding="utf-8")
    snapshot = memory.prompt_snapshot()
    assert "## Durable Memory" in snapshot
    assert "env fact: macOS" in snapshot
    assert "## User Profile" not in snapshot
    assert "stale user fact" not in snapshot


def test_import_from_hermes_skips_user_md(tmp_path: Path, monkeypatch) -> None:
    """import_from_hermes 不再导入 USER.md，只导入 MEMORY.md。"""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "MEMORY.md").write_text("# Env\n- macOS\n", encoding="utf-8")
    (hermes_home / "USER.md").write_text("# User\n- prefers concise\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    memory = LuminaMemory(tmp_path / "lumina")
    imported = memory.import_from_hermes()

    assert imported == {"memory_md": str(hermes_home / "MEMORY.md")}
    assert "- macOS" in memory.read_memory_md()
    # USER.md 不应被导入到 Lumina 的 memories/USER.md
    assert not (tmp_path / "lumina" / "memories" / "USER.md").exists()


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


def test_save_episode_with_reflection_fields(tmp_path):
    """F21: save_episode must accept failure_mode, reflection_text, thread_id."""
    mem = LuminaMemory(tmp_path)
    mem.save_episode(
        episode_id="ep1",
        task="test task",
        steps=[{"thought": "thinking", "tool": "file_read", "output": "ok"}],
        result="result text",
        success=False,
        tools_used=["file_read"],
        failure_mode="verify_failed",
        reflection_text='{"failure_summary": "bad patch", "lesson": "check first"}',
        thread_id="thread-1",
    )
    with mem._connect_session() as conn:
        row = conn.execute("SELECT * FROM episodes WHERE episode_id = ?", ("ep1",)).fetchone()
    assert row["success"] == 0
    assert row["failure_mode"] == "verify_failed"
    assert "bad patch" in row["reflection_text"]
    assert row["thread_id"] == "thread-1"


def test_search_episodes_success_only_filter(tmp_path):
    """F21: search_episodes must support success_only filter."""
    mem = LuminaMemory(tmp_path)
    mem.save_episode("ep1", "deploy task", [], "done", True, ["shell"])
    mem.save_episode("ep2", "deploy task", [], "failed", False, ["patch"],
                     failure_mode="grounding_failed")
    failures = mem.search_episodes("deploy", limit=5, success_only=False)
    assert len(failures) == 1
    assert failures[0]["episode_id"] == "ep2"
    successes = mem.search_episodes("deploy", limit=5, success_only=True)
    assert len(successes) == 1
    assert successes[0]["episode_id"] == "ep1"
    all_eps = mem.search_episodes("deploy", limit=5, success_only=None)
    assert len(all_eps) == 2
