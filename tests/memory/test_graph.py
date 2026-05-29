"""Tests for personal graph builder."""

from pathlib import Path

from secretary.core.types import MemoryChunk, SourceKind
from secretary.memory.db import MemoryStore
from secretary.memory.graph import GraphBuilder
from secretary.memory.kb import KnowledgeWorkspace


def test_personal_graph_contains_center_node(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    workspace = KnowledgeWorkspace(tmp_path / "workspace")
    store.upsert_chunks(
        [
            MemoryChunk(
                chunk_id="1",
                source=SourceKind.XIAOHONGSHU,
                title="小红书推荐 · AI",
                content="AI 工具 效率",
            )
        ]
    )
    workspace.export_chunks(store.list_by_source(SourceKind.XIAOHONGSHU, limit=10))

    graph = GraphBuilder(workspace, store).build(filter_mode="personal")
    node_ids = {node.id for node in graph.nodes}
    assert "entity:me" in node_ids
    assert any(node.node_type == "trait" for node in graph.nodes)
