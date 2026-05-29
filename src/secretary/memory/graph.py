"""Personal knowledge graph builder (NoteAI G3-inspired)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from secretary.core.types import MemoryChunk, SourceKind
from secretary.memory.db import MemoryStore
from secretary.memory.kb import SOURCE_TOPICS, KnowledgeWorkspace
from secretary.memory.profile import ProfileBuilder


@dataclass(frozen=True)
class GraphNode:
    id: str
    name: str
    node_type: str
    meta: dict[str, str | int | bool]


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relation: str


@dataclass(frozen=True)
class GraphData:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    layout: str = "force"


class GraphBuilder:
    """Build topic/tag/personal graphs from KB + memory."""

    def __init__(self, workspace: KnowledgeWorkspace, store: MemoryStore) -> None:
        self._workspace = workspace
        self._store = store

    def build(self, filter_mode: str = "all") -> GraphData:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        seen: set[str] = set()

        if filter_mode in {"topic", "all"}:
            self._append_topic_graph(nodes, edges, seen)
        if filter_mode in {"tag", "all"}:
            self._append_tag_graph(nodes, edges, seen)
        if filter_mode in {"personal", "all"}:
            self._append_personal_graph(nodes, edges, seen)

        return GraphData(nodes=nodes, edges=edges)

    def _append_topic_graph(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen: set[str],
    ) -> None:
        for l1 in self._workspace.topic_tree():
            l1_name = str(l1["name"])
            l1_id = f"t:L1:{l1_name}"
            l1_count = l1.get("file_count", 0)
            l1_file_count = l1_count if isinstance(l1_count, int) else 0
            if l1_id not in seen:
                seen.add(l1_id)
                nodes.append(
                    GraphNode(
                        id=l1_id,
                        name=l1_name,
                        node_type="topic",
                        meta={"level": 1, "file_count": l1_file_count},
                    )
                )
            children = l1.get("children", [])
            if not isinstance(children, list):
                continue
            for l2 in children:
                if not isinstance(l2, dict):
                    continue
                l2_name = str(l2["name"])
                l2_id = f"{l1_id}/{l2_name}"
                l2_count = l2.get("file_count", 0)
                l2_file_count = l2_count if isinstance(l2_count, int) else 0
                if l2_id not in seen:
                    seen.add(l2_id)
                    nodes.append(
                        GraphNode(
                            id=l2_id,
                            name=l2_name,
                            node_type="topic",
                            meta={"level": 2, "file_count": l2_file_count},
                        )
                    )
                edges.append(GraphEdge(source=l1_id, target=l2_id, relation="contains"))
                for file_item in l2.get("files", []):
                    if not isinstance(file_item, dict):
                        continue
                    file_id = f"file:{file_item.get('path', file_item.get('name'))}"
                    if file_id not in seen:
                        seen.add(file_id)
                        nodes.append(
                            GraphNode(
                                id=file_id,
                                name=str(file_item.get("name", "note")),
                                node_type="file",
                                meta={"path": str(file_item.get("path", ""))},
                            )
                        )
                    edges.append(GraphEdge(source=l2_id, target=file_id, relation="owns"))

    def _append_tag_graph(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen: set[str],
    ) -> None:
        tag_files: dict[str, list[str]] = {}
        for note in self._workspace.list_notes():
            for tag in _note_tags(note.path, self._workspace.root):
                tag_files.setdefault(tag, []).append(note.path)
        for tag, paths in tag_files.items():
            tag_id = f"tag:{tag}"
            if tag_id not in seen:
                seen.add(tag_id)
                nodes.append(
                    GraphNode(
                        id=tag_id,
                        name=tag,
                        node_type="tag",
                        meta={"file_count": len(paths)},
                    )
                )
            for rel_path in paths:
                file_id = f"file:{rel_path}"
                if file_id not in seen:
                    seen.add(file_id)
                    nodes.append(
                        GraphNode(
                            id=file_id,
                            name=Path(rel_path).stem,
                            node_type="file",
                            meta={"path": rel_path},
                        )
                    )
                edges.append(GraphEdge(source=tag_id, target=file_id, relation="tags"))

    def _append_personal_graph(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen: set[str],
    ) -> None:
        center_id = "entity:me"
        if center_id not in seen:
            seen.add(center_id)
            nodes.append(
                GraphNode(
                    id=center_id,
                    name="我",
                    node_type="person",
                    meta={"is_center": True},
                )
            )

        profile = ProfileBuilder(self._store).build()
        for section in profile.sections:
            section_id = f"entity:{section.key}"
            if section_id not in seen:
                seen.add(section_id)
                nodes.append(
                    GraphNode(
                        id=section_id,
                        name=section.title,
                        node_type="trait",
                        meta={"evidence_count": section.evidence_count},
                    )
                )
            edges.append(GraphEdge(source=center_id, target=section_id, relation="has_trait"))

        chunks: list[MemoryChunk] = []
        for source in SourceKind:
            chunks.extend(self._store.list_by_source(source, limit=20))
        for chunk in chunks:
            source_id = f"source:{chunk.source.value}"
            if source_id not in seen:
                seen.add(source_id)
                topic_parts = SOURCE_TOPICS.get(chunk.source, ("个人", chunk.source.value))
                nodes.append(
                    GraphNode(
                        id=source_id,
                        name=topic_parts[1],
                        node_type="source",
                        meta={"platform": chunk.source.value},
                    )
                )
                edges.append(GraphEdge(source=center_id, target=source_id, relation="uses"))

            chunk_id = f"chunk:{chunk.chunk_id}"
            if chunk_id not in seen:
                seen.add(chunk_id)
                nodes.append(
                    GraphNode(
                        id=chunk_id,
                        name=chunk.title[:32],
                        node_type="memory",
                        meta={"source": chunk.source.value},
                    )
                )
            edges.append(GraphEdge(source=source_id, target=chunk_id, relation="evidence"))
            trait_key = _source_trait_key(chunk.source)
            trait_id = f"entity:{trait_key}"
            if trait_id in seen:
                edges.append(GraphEdge(source=trait_id, target=chunk_id, relation="supports"))


def _note_tags(rel_path: str, root: Path) -> list[str]:
    text = (root / rel_path).read_text(encoding="utf-8", errors="replace")
    meta, _ = _parse_note_frontmatter(text)
    tags = meta.get("tags", [])
    if isinstance(tags, list):
        return [str(tag) for tag in tags]
    return []


def _parse_note_frontmatter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, object] = {}
    for line in parts[1].strip().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key == "tags":
            try:
                import json

                meta[key] = json.loads(value)
            except Exception:
                meta[key] = []
        else:
            meta[key] = value
    return meta, parts[2]


def _source_trait_key(source: SourceKind) -> str:
    mapping = {
        SourceKind.FEISHU: "work_rhythm",
        SourceKind.EMAIL: "information_habits",
        SourceKind.WEREAD: "reading_taste",
        SourceKind.XIAOHONGSHU: "content_interest",
        SourceKind.WEIXIN_OA: "reading_taste",
        SourceKind.CLOUD_DRIVE: "information_habits",
    }
    return mapping.get(source, "information_habits")
