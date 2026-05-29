"""NoteAI-inspired local knowledge workspace."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from secretary.core.types import MemoryChunk, SourceKind
from secretary.exceptions import IngestError

SOURCE_TOPICS: dict[SourceKind, tuple[str, str]] = {
    SourceKind.FEISHU: ("工作", "飞书"),
    SourceKind.EMAIL: ("信息", "邮箱"),
    SourceKind.WEREAD: ("阅读", "微信读书"),
    SourceKind.XIAOHONGSHU: ("兴趣", "小红书"),
    SourceKind.WEIXIN_OA: ("阅读", "公众号"),
    SourceKind.CLOUD_DRIVE: ("资料", "网盘"),
    SourceKind.LOCAL_DOCUMENTS: ("个人", "本地文档"),
}


@dataclass(frozen=True)
class NoteEntry:
    chunk_id: str
    path: str
    title: str
    topic: str
    source: str
    updated_at: str


class KnowledgeWorkspace:
    """Three-layer workspace: Notes/, wiki/, .ai_memory/."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.notes_dir = root / "Notes"
        self.wiki_dir = root / "wiki"
        self.memory_dir = root / ".ai_memory"
        self.schema_path = root / "schema.md"

    def ensure_layout(self) -> None:
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        if not self.schema_path.exists():
            self.schema_path.write_text(_default_schema(), encoding="utf-8")
        profile_path = self.memory_dir / "user_profile.json"
        if not profile_path.exists():
            profile_path.write_text(
                json.dumps({"profile_md": "", "updated_at": None}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def export_chunks(self, chunks: list[MemoryChunk]) -> int:
        self.ensure_layout()
        written = 0
        for chunk in chunks:
            topic_parts = SOURCE_TOPICS.get(chunk.source, ("个人", chunk.source.value))
            topic = " > ".join(topic_parts)
            folder = self.notes_dir / topic_parts[0] / topic_parts[1]
            folder.mkdir(parents=True, exist_ok=True)
            filename = _safe_filename(chunk.title) + ".md"
            note_path = folder / filename
            frontmatter: dict[str, object] = {
                "topic": topic,
                "tags": [chunk.source.value, topic_parts[0], topic_parts[1]],
                "title": chunk.title,
                "source": chunk.source.value,
                "chunk_id": chunk.chunk_id,
            }
            note_path.write_text(_compose_note(frontmatter, chunk.content), encoding="utf-8")
            written += 1
        self.sync_wiki_index()
        return written

    def sync_wiki_index(self) -> None:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        lines = ["# WIKI 索引", "", f"> 更新时间：{timestamp}", ""]
        for l1 in sorted(self.notes_dir.iterdir()):
            if not l1.is_dir() or l1.name.startswith("."):
                continue
            lines.append(f"- **{l1.name}**")
            for l2 in sorted(l1.iterdir()):
                if not l2.is_dir():
                    continue
                count = sum(1 for item in l2.glob("*.md") if item.is_file())
                lines.append(f"  - {l2.name}（{count} 篇）")
        (self.wiki_dir / "WIKI.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def update_profile_md(self, markdown: str) -> None:
        self.ensure_layout()
        profile_path = self.memory_dir / "user_profile.json"
        payload = {
            "profile_md": markdown,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        profile_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.wiki_dir / "USER_画像.md").write_text(markdown, encoding="utf-8")

    def list_notes(self) -> list[NoteEntry]:
        self.ensure_layout()
        entries: list[NoteEntry] = []
        for path in sorted(self.notes_dir.rglob("*.md")):
            meta, _ = _parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            rel = path.relative_to(self.root).as_posix()
            entries.append(
                NoteEntry(
                    chunk_id=str(meta.get("chunk_id", path.stem)),
                    path=rel,
                    title=str(meta.get("title", path.stem)),
                    topic=str(meta.get("topic", "")),
                    source=str(meta.get("source", "")),
                    updated_at=datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                )
            )
        return entries

    def read_note(self, rel_path: str) -> str:
        target = self._resolve_note_path(rel_path)
        if not target.exists():
            raise IngestError("note not found")
        return target.read_text(encoding="utf-8", errors="replace")

    def write_note(self, rel_path: str, content: str) -> None:
        target = self._resolve_note_path(rel_path)
        if not target.exists():
            raise IngestError("note not found")
        target.write_text(content, encoding="utf-8")
        self.sync_wiki_index()

    def _resolve_note_path(self, rel_path: str) -> Path:
        target = (self.root / rel_path).resolve()
        notes_root = self.notes_dir.resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise IngestError("invalid note path")
        if not target.is_relative_to(notes_root):
            raise IngestError("only notes under Notes/ can be edited")
        return target

    def topic_tree(self) -> list[dict[str, object]]:
        self.ensure_layout()
        tree: list[dict[str, object]] = []
        for l1 in sorted(self.notes_dir.iterdir()):
            if not l1.is_dir() or l1.name.startswith("."):
                continue
            l1_node: dict[str, object] = {
                "name": l1.name,
                "level": 1,
                "children": [],
                "file_count": 0,
            }
            children = l1_node["children"]
            assert isinstance(children, list)
            file_count = l1_node["file_count"]
            assert isinstance(file_count, int)
            for l2 in sorted(l1.iterdir()):
                if not l2.is_dir():
                    continue
                files = [item for item in l2.glob("*.md") if item.is_file()]
                children.append(
                    {
                        "name": l2.name,
                        "level": 2,
                        "path": str(l2),
                        "file_count": len(files),
                        "files": [
                            {
                                "name": item.stem,
                                "path": item.relative_to(self.root).as_posix(),
                            }
                            for item in files
                        ],
                    }
                )
                l1_node["file_count"] = file_count + len(files)
            tree.append(l1_node)
        return tree


def _compose_note(meta: dict[str, object], body: str) -> str:
    tags = meta.get("tags", [])
    tag_yaml = json.dumps(tags, ensure_ascii=False)
    lines = [
        "---",
        f"topic: {meta.get('topic', '')}",
        f"tags: {tag_yaml}",
        f"title: {meta.get('title', '')}",
        f"source: {meta.get('source', '')}",
        f"chunk_id: {meta.get('chunk_id', '')}",
        "---",
        "",
        body.strip(),
        "",
    ]
    return "\n".join(lines)


def _parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
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
                meta[key] = json.loads(value)
            except json.JSONDecodeError:
                meta[key] = [item.strip() for item in value.strip("[]").split(",") if item.strip()]
        else:
            meta[key] = value
    return meta, parts[2].strip()


def _safe_filename(title: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", title).strip()
    return cleaned[:80] or "untitled"


def _default_schema() -> str:
    return """# Lumina Schema

个人知识库宪法：采集 → 整理 → 画像 → 检索。

## 目录
- Notes/ 源稿层（连接器同步写入）
- wiki/ 编译层（WIKI 索引 + USER 画像）
- .ai_memory/ 用户画像 JSON

## 主题
最多三级：`一级 > 二级 > 三级`，由数据源映射自动生成。
"""
