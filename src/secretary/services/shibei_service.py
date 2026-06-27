"""Bridge Lumina agent to the Shibei semantic knowledge base."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from secretary.services.shibei_config import ShibeiConfigStore

logger = logging.getLogger(__name__)

_CANDIDATE_INSTALL_ROOTS = (
    Path.home() / "Documents" / "Projects" / "shibei",
    Path.home() / "Documents" / "My Projects" / "shibei",
)


@dataclass(frozen=True)
class ShibeiImportResult:
    imported: int
    skipped: int
    message: str


class ShibeiService:
    def __init__(self, store: ShibeiConfigStore) -> None:
        self._store = store

    def is_enabled(self) -> bool:
        return self._store.load().enabled

    def is_available(self) -> bool:
        return self._resolve_src_path() is not None

    def status_view(self) -> dict[str, Any]:
        document = self._store.load()
        self._store.sync_yaml(document)
        available = self.is_available()
        source_count = 0
        status = "not_configured"
        message = "未检测到 Shibei 安装"
        if not document.enabled:
            status = "disabled"
            message = "Shibei 知识库已关闭"
        elif not document.sources:
            status = "not_configured"
            message = "请添加需要监控的文件夹"
        elif not available:
            message = (
                "请安装 Shibei（~/Documents/Projects/shibei）或在设置里填写 install_path"
            )
        else:
            try:
                listed = self.list_sources(limit=1)
                source_count = int(listed.get("total", 0))
                status = "ready"
                message = f"已就绪 · 监控 {len(document.sources)} 个文件夹 · 索引 {source_count} 篇"
            except Exception as error:
                status = "error"
                message = f"Shibei 不可用：{error}"

        return {
            "enabled": document.enabled,
            "sources": document.sources,
            "extensions": document.extensions,
            "search_engine": document.search_engine,
            "auto_import_on_sync": document.auto_import_on_sync,
            "collection": document.collection,
            "install_path": document.install_path,
            "config_path": str(self._store.yaml_path),
            "db_path": str(self._store.db_path),
            "status": status,
            "status_message": message,
            "source_count": source_count,
            "shibei_available": available,
        }

    def search(self, query: str, *, limit: int = 5, tag: str | None = None) -> str:
        if not query.strip():
            return "Error: empty query"
        payload = self._call("search", query=query.strip(), limit=limit, tag=tag)
        return _format_search(payload)

    def import_all(self, *, full: bool = False) -> ShibeiImportResult:
        payload = self._call("import_all", full=full)
        imported = int(payload.get("imported", 0))
        skipped = int(payload.get("skipped", 0))
        return ShibeiImportResult(
            imported=imported,
            skipped=skipped,
            message=f"导入 {imported} 篇，跳过 {skipped} 篇",
        )

    def list_sources(self, *, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return self._call("list_sources", limit=limit, offset=offset)

    def _call(self, method: str, **kwargs: Any) -> dict[str, Any]:
        if not self.is_enabled():
            raise RuntimeError("Shibei 知识库未启用")
        src = self._resolve_src_path()
        if src is None:
            raise RuntimeError("未找到 Shibei 安装路径")
        config_path = str(self._store.sync_yaml())
        os.environ["SHIBEI_CONFIG"] = config_path
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        try:
            from shibei import Shibei  # type: ignore[import-untyped]

            brain = Shibei(config_path)
            if method == "search":
                result = brain.search(
                    str(kwargs["query"]),
                    limit=int(kwargs.get("limit", 5)),
                    tag=kwargs.get("tag"),
                )
            elif method == "import_all":
                result = brain.import_all(full=bool(kwargs.get("full", False)))
            elif method == "list_sources":
                result = brain.list_sources(
                    limit=int(kwargs.get("limit", 20)),
                    offset=int(kwargs.get("offset", 0)),
                )
            else:
                raise ValueError(f"unknown shibei method: {method}")
        except ImportError as error:
            raise RuntimeError(
                "无法 import shibei，请确认 install_path 指向 shibei 项目的 src 父目录"
            ) from error
        if not isinstance(result, dict):
            return {"raw": result}
        return result

    def _resolve_src_path(self) -> Path | None:
        document = self._store.load()
        candidates: list[Path] = []
        if document.install_path.strip():
            root = Path(document.install_path.strip()).expanduser()
            candidates.append(root / "src")
            candidates.append(root)
        env_root = os.environ.get("SHIBEI_INSTALL_PATH", "").strip()
        if env_root:
            root = Path(env_root).expanduser()
            candidates.extend([root / "src", root])
        for root in _CANDIDATE_INSTALL_ROOTS:
            candidates.extend([root / "src", root])
        seen: set[Path] = set()
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if (resolved / "shibei" / "__init__.py").is_file():
                return resolved
            if resolved.name == "shibei" and (resolved / "__init__.py").is_file():
                return resolved.parent
        return None


def _format_search(payload: dict[str, Any]) -> str:
    if payload.get("error"):
        return f"Error: {payload['error']}"
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return "未在 Shibei 知识库中找到相关内容。可先 shibei_import 或点「同步」触发导入。"
    lines = [f"Shibei 检索「{payload.get('query', '')}」共 {payload.get('total', len(results))} 条："]
    for item in results[:8]:
        if not isinstance(item, dict):
            continue
        rank = item.get("rank", "?")
        source = item.get("source", "")
        score = item.get("score", "")
        tags = item.get("tags", "")
        text = str(item.get("text", "")).strip().replace("\n", " ")
        if len(text) > 360:
            text = text[:360] + "…"
        lines.append(f"{rank}. {source} (score={score}, tags={tags})")
        lines.append(f"   {text}")
    memories = payload.get("memories")
    if isinstance(memories, list) and memories:
        lines.append("相关记忆：")
        for memory in memories[:3]:
            if isinstance(memory, dict):
                lines.append(f"- [{memory.get('category', '')}] {memory.get('text', '')}")
    return "\n".join(lines)


def format_list_sources(payload: dict[str, Any]) -> str:
    items = payload.get("items") or payload.get("sources") or payload.get("results")
    total = int(payload.get("total", 0))
    if not isinstance(items, list) or not items:
        return f"Shibei 知识库当前为空（total={total}）。请在设置中添加监控文件夹并执行导入。"
    lines = [f"Shibei 已索引 {total or len(items)} 篇文档（展示前 {len(items)} 篇）："]
    for item in items[:20]:
        if isinstance(item, dict):
            path = item.get("source") or item.get("path") or item.get("file", "")
            tags = item.get("tags", "")
            lines.append(f"- {path}" + (f" [{tags}]" if tags else ""))
        else:
            lines.append(f"- {item}")
    return "\n".join(lines)
