"""Tests for Hermes P0 tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from secretary.agent.loop import AgentLoop
from secretary.agent.p0_tools import (
    ClarifyTool,
    PatchTool,
    SearchFilesTool,
    TodoTool,
    is_clarify_output,
)
from secretary.services.todo_store import TodoStore


def test_search_files_finds_content(tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("hello lumina search", encoding="utf-8")
    tool = SearchFilesTool()
    output = tool.execute({"pattern": "lumina", "path": str(tmp_path)}, tmp_path)
    assert "lumina" in output


def test_patch_creates_and_edits_file(tmp_path: Path) -> None:
    tool = PatchTool()
    created = tool.execute(
        {"path": "new.txt", "old_text": "", "new_text": "version 1"},
        tmp_path,
    )
    assert "created" in created
    patched = tool.execute(
        {"path": "new.txt", "old_text": "version 1", "new_text": "version 2"},
        tmp_path,
    )
    assert "patched" in patched
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "version 2"


def test_todo_tool_lifecycle(tmp_path: Path) -> None:
    store = TodoStore(tmp_path / "todos.json")
    tool = TodoTool(store)
    added = tool.execute({"action": "add", "content": "wire P0 tools"}, tmp_path)
    assert "Added todo" in added
    listing = tool.execute({"action": "list"}, tmp_path)
    assert "wire P0 tools" in listing
    item_id = listing.split("]")[1].strip().split(":")[0]
    done = tool.execute({"action": "complete", "id": item_id}, tmp_path)
    assert "Completed" in done


def test_clarify_tool_marks_output(tmp_path: Path) -> None:
    tool = ClarifyTool()
    output = tool.execute({"questions": ["Which file?"]}, tmp_path)
    assert is_clarify_output(output)
    assert "Which file?" in output


def test_agent_loop_stops_on_clarify(tmp_path: Path) -> None:
    from unittest.mock import patch

    clarify = ClarifyTool()
    loop = AgentLoop(
        MagicMock(),
        tools=[clarify],
        max_steps=3,
        working_dir=tmp_path,
    )
    raw = (
        "Need more info.\n"
        "```tool-call\n"
        '{"name": "clarify", "arguments": {"questions": ["目标目录是哪里？"]}}\n'
        "```"
    )
    with patch("secretary.agent.loop.chat_completion", return_value=raw):
        result = loop.run([{"role": "user", "content": "帮我改代码"}], temperature=0.0)
    assert "目标目录" in result.reply
    assert result.used_tools == ["clarify"]
