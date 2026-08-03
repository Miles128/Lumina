"""Pi-aligned read/write/edit tools (+ legacy aliases)."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.confirmation_policy import tool_requires_confirmation
from secretary.agent.p0_tools import EditTool, PatchTool
from secretary.agent.tools.edit_text import apply_unique_edit
from secretary.agent.tools.fs import (
    AliasedTool,
    FileReadTool,
    FileWriteTool,
    ReadTool,
    WriteTool,
)
from secretary.services.file_auth import FileAuthService


def test_canonical_tool_names() -> None:
    assert ReadTool().name == "read"
    assert WriteTool().name == "write"
    assert EditTool().name == "edit"
    assert FileReadTool().name == "read"  # FileReadTool is alias of ReadTool class
    assert FileWriteTool().name == "write"
    assert PatchTool().name == "edit"


def test_aliased_tool_delegates(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("hello\n", encoding="utf-8")
    alias = AliasedTool("file_read", ReadTool())
    out = alias.execute({"path": str(target)}, tmp_path)
    assert "hello" in str(out)


def test_apply_unique_edit_exact_and_unique(tmp_path: Path) -> None:
    path = tmp_path / "f.py"
    path.write_text("def a():\n    return 1\n", encoding="utf-8")
    result = apply_unique_edit(path, old_text="return 1", new_text="return 2")
    assert result.ok
    assert "return 2" in path.read_text(encoding="utf-8")


def test_apply_unique_edit_rejects_multiple_matches(tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_text("x\nx\n", encoding="utf-8")
    result = apply_unique_edit(path, old_text="x", new_text="y")
    assert not result.ok
    assert "occurrences" in (result.error or "").lower() or "2" in (result.error or "")


def test_apply_unique_edit_fuzzy_trailing_whitespace(tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_text("hello world   \n", encoding="utf-8")
    result = apply_unique_edit(path, old_text="hello world", new_text="hi")
    assert result.ok
    assert path.read_text(encoding="utf-8").startswith("hi")


def test_edit_tool_requires_existing_file(tmp_path: Path) -> None:
    out = EditTool().execute(
        {"path": "missing.txt", "oldText": "a", "newText": "b"},
        tmp_path,
    )
    assert "not found" in str(out).lower() or (
        hasattr(out, "error") and out.error and "not found" in out.error.lower()
    )


def test_edit_accepts_legacy_old_text_args(tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_text("abc", encoding="utf-8")
    out = EditTool().execute(
        {"path": str(path), "old_text": "abc", "new_text": "xyz"},
        tmp_path,
    )
    text = out if isinstance(out, str) else (out.content or out.error or "")
    assert "OK" in text or "replaced" in text.lower() or "Successfully" in text
    assert path.read_text(encoding="utf-8") == "xyz"


def test_write_and_edit_need_confirmation(tmp_path: Path) -> None:
    auth = FileAuthService(tmp_path / "auth.json")
    path = tmp_path / "n.txt"
    needs, kind = tool_requires_confirmation(
        WriteTool(),
        {"path": str(path), "content": "x"},
        working_dir=tmp_path,
        file_auth=auth,
        full_fs_access=True,
    )
    assert needs
    assert kind.startswith("write")
    path.write_text("a", encoding="utf-8")
    needs2, _ = tool_requires_confirmation(
        EditTool(),
        {"path": str(path), "oldText": "a", "newText": "b"},
        working_dir=tmp_path,
        file_auth=auth,
        full_fs_access=True,
    )
    assert needs2
