"""Tests for knowledge workspace note editing."""

from pathlib import Path

import pytest

from secretary.core.types import MemoryChunk, SourceKind
from secretary.exceptions import IngestError
from secretary.memory.kb import KnowledgeWorkspace


def test_write_note_updates_file(tmp_path: Path) -> None:
    workspace = KnowledgeWorkspace(tmp_path / "workspace")
    chunks = [
        MemoryChunk(
            chunk_id="abc",
            source=SourceKind.WEREAD,
            title="微信读书 · 深度工作",
            content="专注是稀缺资源",
            metadata={},
        )
    ]
    workspace.export_chunks(chunks)
    note_path = workspace.list_notes()[0].path
    updated = "---\ntitle: edited\n---\n\n新内容"
    workspace.write_note(note_path, updated)
    assert workspace.read_note(note_path) == updated


def test_write_note_rejects_outside_notes(tmp_path: Path) -> None:
    workspace = KnowledgeWorkspace(tmp_path / "workspace")
    workspace.ensure_layout()
    with pytest.raises(IngestError):
        workspace.write_note("wiki/WIKI.md", "hack")
