"""Tests for knowledge workspace."""

from pathlib import Path

from secretary.core.types import MemoryChunk, SourceKind
from secretary.memory.kb import KnowledgeWorkspace


def test_knowledge_workspace_export_and_tree(tmp_path: Path) -> None:
    workspace = KnowledgeWorkspace(tmp_path / "workspace")
    chunks = [
        MemoryChunk(
            chunk_id="abc",
            source=SourceKind.WEREAD,
            title="微信读书 · 深度工作",
            content="专注是稀缺资源",
            metadata={"book_title": "深度工作"},
        )
    ]
    written = workspace.export_chunks(chunks)
    assert written == 1

    notes = workspace.list_notes()
    assert len(notes) == 1
    assert notes[0].source == SourceKind.WEREAD.value

    tree = workspace.topic_tree()
    assert len(tree) == 1
    assert tree[0]["name"] == "阅读"

    content = workspace.read_note(notes[0].path)
    assert "专注是稀缺资源" in content
