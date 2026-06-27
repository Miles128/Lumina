"""Tests for list_dir tool output semantics."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.loop import ListDirTool


def test_list_dir_shows_names_without_lock_for_readable_entries(tmp_path: Path) -> None:
    (tmp_path / "Lumina").mkdir()
    (tmp_path / "Other").mkdir()
    (tmp_path / "readme.md").write_text("hello", encoding="utf-8")

    tool = ListDirTool()
    output = tool.execute({"path": str(tmp_path)}, tmp_path)

    assert "🔒" not in output
    assert "Lumina" in output
    assert "readme.md" in output
    assert "不要对用户声称灵犀" in output
