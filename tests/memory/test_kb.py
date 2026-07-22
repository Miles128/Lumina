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


def test_knowledge_workspace_aggregates_chunks_by_topic(tmp_path: Path) -> None:
    workspace = KnowledgeWorkspace(tmp_path / "workspace")
    chunks = [
        MemoryChunk(
            chunk_id="abc",
            source=SourceKind.WEREAD,
            title="深度工作",
            content="专注是稀缺资源",
            metadata={},
        ),
        MemoryChunk(
            chunk_id="def",
            source=SourceKind.WEREAD,
            title="原则",
            content="用原则做决策",
            metadata={},
        ),
    ]

    written = workspace.export_chunks(chunks)

    assert written == 2
    note_files = list((tmp_path / "workspace" / "Notes" / "阅读" / "微信读书").glob("*.md"))
    assert [path.name for path in note_files] == ["微信读书.md"]
    notes = workspace.list_notes()
    assert len(notes) == 1
    assert notes[0].chunk_id == "aggregate:阅读:微信读书"
    content = workspace.read_note(notes[0].path)
    assert "## 深度工作" in content
    assert "## 原则" in content
    assert "chunk_id: `abc`" in content
    assert "chunk_id: `def`" in content


def test_knowledge_workspace_archives_legacy_per_chunk_notes(tmp_path: Path) -> None:
    workspace = KnowledgeWorkspace(tmp_path / "workspace")
    legacy_dir = tmp_path / "workspace" / "Notes" / "阅读" / "微信读书"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "深度工作.md"
    legacy_file.write_text(
        "---\n"
        "topic: 阅读 > 微信读书\n"
        "tags: [\"weread\"]\n"
        "title: 深度工作\n"
        "source: weread\n"
        "chunk_id: abc\n"
        "---\n\n"
        "旧内容\n",
        encoding="utf-8",
    )

    workspace.export_chunks(
        [
            MemoryChunk(
                chunk_id="abc",
                source=SourceKind.WEREAD,
                title="深度工作",
                content="新内容",
                metadata={},
            )
        ]
    )

    assert not legacy_file.exists()
    assert (legacy_dir / "微信读书.md").exists()
    archived = tmp_path / "workspace" / ".ai_memory" / "legacy_notes" / "阅读" / "微信读书" / "深度工作.md"
    assert archived.exists()
