"""Pi naming, move tool, and confirm-diff preview."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.confirmation_policy import tool_requires_confirmation
from secretary.agent.p0_tools import GlobFilesTool, SearchFilesTool
from secretary.agent.tools.edit_text import build_confirm_diff_preview, format_line_diff
from secretary.agent.tools.fs import ListDirTool, MoveTool, WriteTool
from secretary.services.file_auth import FileAuthService


def test_canonical_discovery_tool_names() -> None:
    assert ListDirTool().name == "ls"
    assert SearchFilesTool().name == "grep"
    assert GlobFilesTool().name == "glob"


def test_move_tool_moves_file(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("hi", encoding="utf-8")
    dst = tmp_path / "sub" / "b.txt"
    out = MoveTool().execute(
        {"from_path": str(src), "to_path": str(dst)},
        tmp_path,
    )
    assert "OK" in str(out)
    assert not src.exists()
    assert dst.read_text(encoding="utf-8") == "hi"


def test_move_refuses_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    dst = tmp_path / "b.txt"
    src.write_text("1", encoding="utf-8")
    dst.write_text("2", encoding="utf-8")
    out = MoveTool().execute(
        {"from_path": str(src), "to_path": str(dst)},
        tmp_path,
    )
    assert hasattr(out, "error") and out.error
    assert "exists" in out.error.lower()


def test_move_requires_confirmation(tmp_path: Path) -> None:
    needs, kind = tool_requires_confirmation(
        MoveTool(),
        {"from_path": "a", "to_path": "b"},
        working_dir=tmp_path,
        file_auth=FileAuthService(tmp_path / "auth.json"),
    )
    assert needs
    assert kind == "write_move"


def test_confirm_diff_preview_for_write_and_edit(tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_text("hello\n", encoding="utf-8")
    write_diff = build_confirm_diff_preview(
        "write",
        {"path": str(path), "content": "world\n"},
        tmp_path,
    )
    assert "---" in write_diff and "+++" in write_diff
    assert "-hello" in write_diff or "-hello\n" in write_diff + "\n"
    assert "+world" in write_diff

    edit_diff = build_confirm_diff_preview(
        "edit",
        {"path": str(path), "oldText": "hello", "newText": "hi"},
        tmp_path,
    )
    assert "+++" in edit_diff
    assert path.read_text(encoding="utf-8") == "hello\n"  # dry-run only


def test_format_line_diff_empty_when_identical() -> None:
    assert format_line_diff("a", "a") == ""


def test_write_creates_without_side_effect_in_preview(tmp_path: Path) -> None:
    target = tmp_path / "new.txt"
    preview = build_confirm_diff_preview(
        "write",
        {"path": str(target), "content": "x\n"},
        tmp_path,
    )
    assert not target.exists()
    assert "+x" in preview
    WriteTool().execute({"path": str(target), "content": "x\n"}, tmp_path)
    assert target.exists()
