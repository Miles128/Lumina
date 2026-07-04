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


@dataclass(frozen=True)
class ShibeiImportResult:
    imported: int
    skipped: int
    message: str


def shibei_ready_for_memory_read(service: ShibeiService | None) -> bool:
    """True when Lumina should read personal docs via Shibei instead of requiring connector sync."""
    if service is None or not service.is_enabled() or not service.is_available():
        return False
    return service._store.resolve_config_path().is_file()


class ShibeiService:
    def __init__(self, store: ShibeiConfigStore) -> None:
        self._store = store

    def is_enabled(self) -> bool:
        return self._store.load().enabled

    def is_available(self) -> bool:
        return self._resolve_src_path() is not None

    def status_view(self) -> dict[str, Any]:
        document = self._store.load()
        available = self.is_available()
        config_path = self._store.resolve_config_path(document)
        native = self._try_native_config()
        sources = list(native.sources) if native else []
        extensions = list(native.extensions) if native else []
        chroma = getattr(native, "chroma", None)
        search_engine = str(getattr(chroma, "search_engine", "bm25"))
        collection = str(getattr(chroma, "collection", "knowledge_base"))
        db_path = str(getattr(native, "chroma_path_expanded", Path("~/.shibei/db").expanduser()))
        source_count = 0
        status = "not_configured"
        message = "未检测到 Shibei 安装"
        if not document.enabled:
            status = "disabled"
            message = "Shibei 知识库已关闭"
        elif not config_path.is_file():
            status = "not_configured"
            message = "未找到 Shibei config.yaml，请填写 Shibei 安装路径"
        elif not available:
            message = (
                "请安装 Shibei（~/Documents/Projects/shibei）或在设置里填写 install_path"
            )
        elif not sources:
            status = "not_configured"
            message = "Shibei config.yaml 中未配置 sources"
        else:
            try:
                listed = self.list_sources(limit=1)
                source_count = int(listed.get("count", listed.get("total", 0)))
                status = "ready"
                message = (
                    f"已连接 Shibei · 监控 {len(sources)} 个文件夹 · 索引 {source_count} 篇"
                )
                noise = shibei_sources_noise_warning(sources)
                if noise:
                    message = f"{message} · {noise}"
            except Exception as error:
                status = "error"
                message = f"Shibei 不可用：{error}"

        return {
            "enabled": document.enabled,
            "sources": sources,
            "extensions": extensions,
            "search_engine": search_engine,
            "auto_import_on_sync": document.auto_import_on_sync,
            "collection": collection,
            "install_path": document.install_path,
            "config_path": str(config_path),
            "db_path": db_path,
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
        imported = int(payload.get("imported", payload.get("files", 0)))
        skipped = int(payload.get("skipped", 0))
        return ShibeiImportResult(
            imported=imported,
            skipped=skipped,
            message=f"导入 {imported} 篇，跳过 {skipped} 篇",
        )

    def list_sources(self, *, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return self._call("list_sources", limit=limit, offset=offset)

    def search_raw(self, query: str, *, limit: int = 10, tag: str | None = None) -> dict[str, Any]:
        if not query.strip():
            payload: dict[str, Any] = {"query": "", "total": 0, "results": []}
            payload["empty_state"] = shibei_empty_state("", self.status_view())
            return payload
        payload = self._call("search", query=query.strip(), limit=limit, tag=tag)
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            payload["empty_state"] = shibei_empty_state(query.strip(), self.status_view())
        return payload

    def read_source(self, path: str, *, max_chars: int = 120_000) -> dict[str, str]:
        resolved = Path(path).expanduser().resolve()
        roots = self._source_roots()
        if not roots:
            raise ValueError("Shibei config.yaml 未配置 sources")
        if not any(
            resolved == root or root in resolved.parents
            for root in roots
            if root.is_dir()
        ):
            raise ValueError("文件不在 Shibei 监控范围内")
        if not resolved.is_file():
            raise FileNotFoundError(path)
        content = resolved.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n…（已截断）"
        return {"path": str(resolved), "name": resolved.name, "content": content}

    def _source_roots(self) -> list[Path]:
        native = self._try_native_config()
        if native is None:
            return []
        roots: list[Path] = []
        for source in native.sources:
            cleaned = str(source).strip()
            if not cleaned:
                continue
            roots.append(Path(cleaned).expanduser().resolve())
        return roots

    def _try_native_config(self) -> Any | None:
        config_path = self._store.resolve_config_path()
        if not config_path.is_file():
            return None
        src = self._resolve_src_path()
        if src is None:
            return None
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        try:
            from shibei.config import load_config
        except ImportError:
            return None
        return load_config(str(config_path))

    def _call(self, method: str, **kwargs: Any) -> dict[str, Any]:
        if not self.is_enabled():
            raise RuntimeError("Shibei 知识库未启用")
        src = self._resolve_src_path()
        if src is None:
            raise RuntimeError("未找到 Shibei 安装路径")
        config_path = str(self._store.resolve_config_path())
        if not Path(config_path).is_file():
            raise RuntimeError(f"未找到 Shibei 配置文件：{config_path}")
        os.environ["SHIBEI_CONFIG"] = config_path
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        try:
            from shibei import Shibei

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
        install_root = self._store.resolve_install_root(document)
        if install_root is not None:
            candidates.extend([install_root / "src", install_root])
        if document.install_path.strip():
            root = Path(document.install_path.strip()).expanduser()
            candidates.extend([root / "src", root])
        env_root = os.environ.get("SHIBEI_INSTALL_PATH", "").strip()
        if env_root:
            root = Path(env_root).expanduser()
            candidates.extend([root / "src", root])
        seen: set[Path] = set()
        for candidate in candidates:
            if not candidate.exists():
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if (resolved / "shibei" / "__init__.py").is_file():
                return resolved
            if resolved.name == "shibei" and (resolved / "__init__.py").is_file():
                return resolved.parent
        return None


SHIBEI_EMPTY_HINT = (
    "未在 Shibei 知识库中找到相关内容。\n"
    "建议：\n"
    "1. 设置 → Shibei 知识库：确认 sources 已配置\n"
    "2. 让 Agent 调用 shibei_import 增量导入，或在 Shibei 应用中 import\n"
    "3. 打开「知识库」页查看索引是否为空"
)

SHIBEI_EMPTY_ACTIONS: tuple[dict[str, str], ...] = (
    {
        "id": "import",
        "label": "导入",
        "description": "增量扫描 Shibei config.yaml 中的 sources。",
    },
    {
        "id": "settings",
        "label": "检查设置",
        "description": "确认 Shibei 安装路径、config.yaml 和 sources。",
    },
    {
        "id": "broaden",
        "label": "换关键词",
        "description": "减少限定词，尝试标题、项目名或人名。",
    },
)

SHIBEI_NOISE_DIR_NAMES = frozenset(
    {"target", "node_modules", ".git", "dist", "build", "__pycache__", ".venv", "venv"}
)


def shibei_sources_noise_warning(sources: list[str]) -> str:
    """Warn when monitored paths likely include build artifacts (config hygiene)."""
    hits: list[str] = []
    for source in sources:
        parts = {part.lower() for part in Path(source).expanduser().parts}
        overlap = parts & SHIBEI_NOISE_DIR_NAMES
        if overlap:
            hits.append(f"{source}（含 {', '.join(sorted(overlap))}）")
    if not hits:
        return ""
    return (
        "建议在 Shibei config.yaml 的 ignore 中排除构建目录，避免索引噪音："
        + "；".join(hits[:3])
    )


def is_shibei_empty_result(text: str) -> bool:
    cleaned = text.strip()
    return cleaned.startswith("未在 Shibei 知识库中找到")


def shibei_empty_state(query: str, status: dict[str, Any] | None = None) -> dict[str, Any]:
    status = status or {}
    source_count = int(status.get("source_count") or 0)
    sources = status.get("sources")
    source_total = len(sources) if isinstance(sources, list) else 0
    reason = "no_results"
    message = "没有找到匹配内容。可以先导入索引，或换一组更宽的关键词。"
    if status.get("status") != "ready":
        reason = str(status.get("status") or "not_ready")
        message = str(status.get("status_message") or "Shibei 尚未就绪，请先检查配置。")
    elif source_count <= 0:
        reason = "empty_index"
        message = "Shibei 已连接，但当前索引为空。请先导入监控文件夹。"
    elif source_total <= 0:
        reason = "no_sources"
        message = "Shibei config.yaml 未配置 sources。请先添加监控文件夹。"
    return {
        "query": query,
        "reason": reason,
        "message": message,
        "actions": [dict(item) for item in SHIBEI_EMPTY_ACTIONS],
    }


def _format_search(payload: dict[str, Any]) -> str:
    if payload.get("error"):
        return f"Error: {payload['error']}"
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return SHIBEI_EMPTY_HINT
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
    total = int(payload.get("count", payload.get("total", 0)))
    if not isinstance(items, list) or not items:
        return f"Shibei 知识库当前为空（total={total}）。请在 Shibei 中配置 sources 并执行 import。"
    lines = [f"Shibei 已索引 {total or len(items)} 篇文档（展示前 {len(items)} 篇）："]
    for item in items[:20]:
        if isinstance(item, dict):
            path = item.get("source") or item.get("path") or item.get("file", "")
            tags = item.get("tags", "")
            lines.append(f"- {path}" + (f" [{tags}]" if tags else ""))
        else:
            lines.append(f"- {item}")
    return "\n".join(lines)
