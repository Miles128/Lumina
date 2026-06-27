"""Persistent Shibei knowledge-base configuration for Lumina."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from secretary.config import Settings
from secretary.exceptions import SecretaryError

DEFAULT_EXTENSIONS = (".md", ".txt", ".docx", ".xlsx", ".csv")


class ShibeiConfigDocument(BaseModel):
    enabled: bool = True
    sources: list[str] = Field(default_factory=list)
    extensions: list[str] = Field(default_factory=lambda: list(DEFAULT_EXTENSIONS))
    search_engine: str = Field(default="bm25", pattern="^(bm25|vector|hybrid)$")
    auto_import_on_sync: bool = True
    collection: str = "lumina_kb"
    install_path: str = ""


@dataclass(frozen=True)
class ShibeiConfigView:
    enabled: bool
    sources: list[str]
    extensions: list[str]
    search_engine: str
    auto_import_on_sync: bool
    collection: str
    install_path: str
    config_path: str
    db_path: str
    status: str
    status_message: str
    source_count: int
    shibei_available: bool


class ShibeiConfigStore:
    def __init__(self, config_path: Path, *, data_dir: Path) -> None:
        self._path = config_path
        self._data_dir = data_dir
        self._yaml_dir = data_dir / "shibei"
        self._yaml_path = self._yaml_dir / "config.yaml"

    @property
    def yaml_path(self) -> Path:
        return self._yaml_path

    @property
    def db_path(self) -> Path:
        return self._yaml_dir / "db"

    def load(self) -> ShibeiConfigDocument:
        if not self._path.exists():
            return self._default_document()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SecretaryError(f"invalid shibei config: {self._path}") from exc
        document = ShibeiConfigDocument.model_validate(raw)
        if not document.sources:
            document = document.model_copy(update={"sources": self._default_sources()})
        return document

    def save(self, document: ShibeiConfigDocument) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            document.model_dump_json(indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self.sync_yaml(document)

    def update(self, payload: dict[str, object]) -> ShibeiConfigDocument:
        current = self.load()
        merged = current.model_dump()
        for key, value in payload.items():
            if key not in merged or value is None:
                continue
            merged[key] = value
        document = ShibeiConfigDocument.model_validate(merged)
        self.save(document)
        return document

    def sync_yaml(self, document: ShibeiConfigDocument | None = None) -> Path:
        document = document or self.load()
        self._yaml_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Lumina-managed Shibei config — 监控文件夹在设置 → Shibei 知识库 中修改",
            "chroma:",
            f"  path: {self.db_path}",
            f"  collection: {document.collection}",
            f"  search_engine: {document.search_engine}",
            "embedding:",
            "  model: moka-ai/m3e-base",
            "  device: cpu",
            "  hf_endpoint: https://hf-mirror.com",
            "sources:",
        ]
        for source in document.sources:
            cleaned = str(source).strip()
            if cleaned:
                lines.append(f"  - {cleaned}")
        if not any(str(item).strip() for item in document.sources):
            lines.append(f"  - {Path.home() / 'Documents'}")
        lines.append("extensions:")
        for ext in document.extensions:
            cleaned = str(ext).strip()
            if cleaned:
                lines.append(f"  - {cleaned}")
        lines.extend(
            [
                "chunking:",
                "  max_chars: 800",
                '  split_pattern: "\\n(?=## )"',
                "tagging:",
                "  rules:",
                '    - pattern: ".*"',
                "      tag: lumina",
            ]
        )
        self._yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self._yaml_path

    def _default_document(self) -> ShibeiConfigDocument:
        return ShibeiConfigDocument(sources=self._default_sources())

    def _default_sources(self) -> list[str]:
        settings = Settings()
        projects = settings.projects_dir.strip()
        sources: list[str] = []
        if projects:
            sources.append(projects)
        docs = Path.home() / "Documents"
        if docs.is_dir() and str(docs) not in sources:
            sources.append(str(docs))
        return sources
