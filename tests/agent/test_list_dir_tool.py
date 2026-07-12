"""Tests for list_dir tool output semantics."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.loop import FileReadTool, ListDirTool
from secretary.agent.tools.base import _resolve_path
from secretary.agent.tools.fs import FileWriteTool


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


def test_resolve_path_expands_tilde(tmp_path: Path) -> None:
    home = Path.home()
    assert _resolve_path("~", tmp_path) == home.resolve()
    assert _resolve_path("~/Documents", tmp_path) == (home / "Documents").resolve()
    # Relative paths still join working_dir (must not treat "~" as a literal segment).
    assert _resolve_path("subdir", tmp_path) == (tmp_path / "subdir").resolve()
    assert "~" not in str(_resolve_path("~/Documents", tmp_path))


def test_list_dir_expands_tilde_home(tmp_path: Path) -> None:
    marker = f"lumina-tilde-list-{tmp_path.name}"
    probe = Path.home() / marker
    probe.mkdir(exist_ok=True)
    try:
        (probe / "prd-first-marker.txt").write_text("ok", encoding="utf-8")
        tool = ListDirTool()
        output = tool.execute({"path": f"~/{marker}"}, tmp_path)
        assert "path not found" not in str(output).lower()
        assert "prd-first-marker.txt" in str(output)
        assert f"{Path.home() / marker}" in str(output) or marker in str(output)
    finally:
        (probe / "prd-first-marker.txt").unlink(missing_ok=True)
        probe.rmdir()


def test_file_read_expands_tilde(tmp_path: Path) -> None:
    marker = f"lumina-tilde-read-{tmp_path.name}.txt"
    probe = Path.home() / marker
    probe.write_text("hello-from-home\n", encoding="utf-8")
    try:
        tool = FileReadTool()
        output = tool.execute({"path": f"~/{marker}"}, tmp_path)
        assert "file not found" not in str(output).lower()
        assert "hello-from-home" in str(output)
    finally:
        probe.unlink(missing_ok=True)


def test_file_write_describe_expands_tilde(tmp_path: Path) -> None:
    tool = FileWriteTool()
    desc = tool.describe_action(
        {"path": "~/Documents/example.txt", "content": "x"},
        tmp_path,
    )
    assert "~" not in desc.split("`")[1]
    assert str(Path.home() / "Documents" / "example.txt") in desc
