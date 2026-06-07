"""Discover, install, and manage agent skills (Hermes/Cursor/Claude compatible)."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from typing import Any

from secretary.exceptions import AgentError

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SCALAR = re.compile(r"^([A-Za-z0-9_-]+):\s*(.+?)\s*$", re.MULTILINE)

AGENT_SCAN_ROOTS: tuple[Path, ...] = (
    Path.home() / ".hermes",
    Path.home() / ".cursor",
    Path.home() / ".claude",
    Path.home() / ".agents",
)

SKILL_CATEGORIES: tuple[str, ...] = (
    "开发",
    "设计",
    "内容",
    "办公协同",
    "自动化",
    "数据分析",
    "系统工具",
    "其他",
)

_CATEGORY_RULES: dict[str, tuple[str, ...]] = {
    "开发": ("sdk", "api", "debug", "code", "ci", "git", "mcp", "test", "agent"),
    "设计": ("figma", "design", "ui", "ux", "canvas", "prototype", "slides"),
    "内容": ("writer", "article", "wechat", "copy", "content", "redbook"),
    "办公协同": ("lark", "calendar", "mail", "task", "sheets", "doc", "wiki"),
    "自动化": ("automation", "loop", "workflow", "hook", "autocli", "browser"),
    "数据分析": ("datadog", "metrics", "analysis", "report", "investigator"),
    "系统工具": ("statusline", "settings", "rule", "skill-maker", "filesystem"),
}

SKIP_SCAN_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".Trash",
    "Library",
    "$RECYCLE.BIN",
    "vendor",
    "dist",
    "build",
    "target",
    ".venv",
    "venv",
    "coverage",
    ".next",
    ".nuxt",
    "DerivedData",
    "Pods",
    "site-packages",
    "egg-info",
}


@dataclass(frozen=True)
class SkillRecord:
    name: str
    description: str
    path: str
    source_key: str
    source_label: str
    source_root: str
    origin_path: str
    install_mode: str
    link_target: str
    status: str
    category: str
    tags: tuple[str, ...]
    installed: bool = False


@dataclass(frozen=True)
class InstallAllResult:
    installed: int
    skipped: int
    failed: list[str]


class SkillManager:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._skills_dir = data_dir / "skills"
        self._index_path = data_dir / "skills_index.json"

    @property
    def skills_dir(self) -> Path:
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        return self._skills_dir

    def list_sources(self) -> list[dict[str, object]]:
        catalog = self.catalog()
        counts: dict[str, int] = {}
        labels: dict[str, str] = {}
        for item in catalog:
            counts[item.source_key] = counts.get(item.source_key, 0) + 1
            labels[item.source_key] = item.source_label
        items: list[dict[str, object]] = [
            {
                "key": "all",
                "label": "全部来源",
                "path": ", ".join(str(root) for root in AGENT_SCAN_ROOTS),
                "available": any(root.exists() for root in AGENT_SCAN_ROOTS),
                "count": len(catalog),
            }
        ]
        for key in sorted(counts, key=lambda value: labels.get(value, value)):
            root = _source_root(key)
            items.append(
                {
                    "key": key,
                    "label": labels[key],
                    "path": str(root) if root else "",
                    "available": bool(root and root.exists()) or counts[key] > 0,
                    "count": counts[key],
                }
            )
        return items

    def categories(self) -> list[str]:
        return list(SKILL_CATEGORIES)

    def catalog(self, source_key: str | None = None) -> list[SkillRecord]:
        installed_index = self._installed_index()
        records: list[SkillRecord] = []
        seen_folders: set[Path] = set()
        for skill_md in _iter_skill_files():
            folder = skill_md.parent.resolve()
            if folder in seen_folders:
                continue
            seen_folders.add(folder)
            key, label = _classify_path(folder)
            if source_key and source_key != "all" and key != source_key:
                continue
            meta = parse_skill_markdown(skill_md.read_text(encoding="utf-8", errors="replace"))
            name = meta.get("name") or folder.name
            description = (meta.get("description") or "无描述")[:240]
            installed_record = installed_index.get(name.lower()) or installed_index.get(folder.name.lower())
            category, tags = self._classify(name, description, folder)
            records.append(
                SkillRecord(
                    name=name,
                    description=description,
                    path=str(folder),
                    source_key=key,
                    source_label=label,
                    source_root=str(_source_root(key) or folder),
                    origin_path=str(folder),
                    install_mode=installed_record.install_mode if installed_record else "none",
                    link_target=installed_record.link_target if installed_record else "",
                    status=installed_record.status if installed_record else "available",
                    category=category,
                    tags=tags,
                    installed=installed_record is not None,
                )
            )
        records.sort(key=lambda item: (item.source_label, item.name.lower()))
        return records

    def list_installed(self) -> list[SkillRecord]:
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        records: list[SkillRecord] = []
        for entry in os.scandir(self.skills_dir):
            if not entry.is_dir(follow_symlinks=False) and not entry.is_symlink():
                continue
            record = self._build_installed_record(entry)
            if record is not None:
                records.append(record)

        conflicts: dict[str, int] = {}
        for item in records:
            conflicts[item.name.lower()] = conflicts.get(item.name.lower(), 0) + 1
        normalized: list[SkillRecord] = []
        for item in records:
            status = "conflict" if conflicts[item.name.lower()] > 1 else item.status
            normalized.append(
                SkillRecord(
                    name=item.name,
                    description=item.description,
                    path=item.path,
                    source_key=item.source_key,
                    source_label=item.source_label,
                    source_root=item.source_root,
                    origin_path=item.origin_path,
                    install_mode=item.install_mode,
                    link_target=item.link_target,
                    status=status,
                    category=item.category,
                    tags=item.tags,
                    installed=True,
                )
            )
        normalized.sort(key=lambda item: item.name.lower())
        return normalized

    def install(
        self,
        source_path: str,
        target_name: str | None = None,
        install_mode: str = "link",
    ) -> SkillRecord:
        source = Path(source_path).expanduser().resolve()
        skill_md = source / "SKILL.md"
        if not skill_md.exists():
            raise AgentError("所选目录不是有效技能（缺少 SKILL.md）")
        if not _is_allowed_source(source):
            raise AgentError("只能从灵犀扫描到的 Agent 技能目录挂靠")

        mode = "copy" if install_mode == "copy" else "link"
        meta = parse_skill_markdown(skill_md.read_text(encoding="utf-8", errors="replace"))
        folder_name = self._unique_install_name(target_name or source.name, meta.get("name") or source.name)
        dest = self.skills_dir / folder_name
        if dest.exists() or dest.is_symlink():
            raise AgentError(f"技能已存在：{folder_name}")
        try:
            if mode == "link":
                os.symlink(source, dest, target_is_directory=True)
            else:
                shutil.copytree(source, dest)
        except OSError as exc:
            raise AgentError(f"安装失败：{exc}") from exc

        installed = self.list_installed()
        for item in installed:
            if Path(item.path).name == folder_name:
                return item
        raise AgentError("安装完成但无法读取技能信息")

    def install_all(self, source_key: str | None = None, install_mode: str = "link") -> InstallAllResult:
        items = self.catalog(source_key)
        installed = 0
        skipped = 0
        failed: list[str] = []
        for item in items:
            if item.installed:
                skipped += 1
                continue
            try:
                self.install(item.path, install_mode=install_mode)
                installed += 1
            except AgentError as error:
                failed.append(f"{item.name}: {error}")
        return InstallAllResult(installed=installed, skipped=skipped, failed=failed)

    def uninstall(self, name: str) -> None:
        folder = self._resolve_installed_folder(name)
        if folder.is_symlink():
            folder.unlink(missing_ok=False)
            return
        shutil.rmtree(folder)

    def update_category(self, name: str, category: str, tags: list[str] | None = None) -> None:
        cleaned_category = category.strip() if category.strip() in SKILL_CATEGORIES else "其他"
        cleaned_tags = [tag.strip() for tag in (tags or []) if tag.strip()][:8]
        payload: dict[str, Any] = self._load_index()
        overrides: dict[str, Any] = payload.setdefault("category_overrides", {})
        overrides[name.lower()] = {
            "category": cleaned_category,
            "tags": cleaned_tags,
        }
        self._save_index(payload)

    def read_skill_body(self, name: str, max_chars: int = 4000) -> str:
        folder = self._resolve_installed_folder(name)
        if folder.is_symlink() and not folder.exists():
            raise AgentError(f"技能链接已失效：{folder}")
        skill_md = folder / "SKILL.md"
        if not skill_md.exists():
            raise AgentError(f"技能缺少 SKILL.md：{folder}")
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        if text.startswith("---"):
            match = _FRONTMATTER.match(text)
            body = text[match.end() :] if match else text
        else:
            body = text
        cleaned = body.strip()
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[: max_chars - 1].rstrip() + "…"

    def prompt_block(self, max_skills: int = 8, max_chars_each: int = 900) -> str:
        installed = [item for item in self.list_installed() if item.status in {"ok", "conflict"}]
        if not installed:
            return "当前未安装技能。打开「技能」面板，点「一键挂靠全部」即可导入。"
        lines = ["已安装技能（按需参考，不要编造未提供的能力）："]
        for item in installed[:max_skills]:
            body = self.read_skill_body(item.name, max_chars=max_chars_each)
            lines.append(f"\n### Skill: {item.name}\n{item.description}\n{body}")
        return "\n".join(lines)

    def _installed_index(self) -> dict[str, SkillRecord]:
        index: dict[str, SkillRecord] = {}
        for item in self.list_installed():
            index[item.name.lower()] = item
            index[Path(item.path).name.lower()] = item
        return index

    def _build_installed_record(self, entry: os.DirEntry[str]) -> SkillRecord | None:
        path = Path(entry.path)
        is_link = entry.is_symlink()
        install_mode = "link" if is_link else "copy"
        link_target = ""
        status = "ok"
        origin = path

        if is_link:
            try:
                raw_target = os.readlink(entry.path)
            except OSError:
                status = "broken_link"
                raw_target = ""
            if raw_target:
                target = Path(raw_target)
                if not target.is_absolute():
                    target = (path.parent / target).resolve()
                else:
                    target = target.resolve()
                link_target = str(target)
                origin = target
                if not target.exists():
                    status = "broken_link"
        if status != "broken_link" and not path.exists():
            status = "broken_link"

        skill_dir = origin if origin.exists() else path
        skill_md = skill_dir / "SKILL.md"
        meta: dict[str, str] = {}
        if skill_md.exists():
            meta = parse_skill_markdown(skill_md.read_text(encoding="utf-8", errors="replace"))
        elif status == "ok":
            status = "missing_skill_md"

        name = meta.get("name") or path.name
        description = (meta.get("description") or "无描述")[:240]
        source_key, source_label = _classify_path(origin)
        category, tags = self._classify(name, description, origin)
        return SkillRecord(
            name=name,
            description=description,
            path=str(path),
            source_key=source_key,
            source_label=source_label,
            source_root=str(_source_root(source_key) or origin),
            origin_path=str(origin),
            install_mode=install_mode,
            link_target=link_target,
            status=status,
            category=category,
            tags=tags,
            installed=True,
        )

    def _classify(self, name: str, description: str, path: Path) -> tuple[str, tuple[str, ...]]:
        payload: dict[str, Any] = self._load_index()
        overrides: dict[str, Any] = payload.get("category_overrides", {})
        override: dict[str, Any] | None = overrides.get(name.lower()) if isinstance(overrides, dict) else None
        if isinstance(override, dict):
            category = str(override.get("category") or "其他")
            tags = override.get("tags") or []
            if category not in SKILL_CATEGORIES:
                category = "其他"
            normalized_tags = tuple(str(tag).strip() for tag in tags if str(tag).strip())
            return category, normalized_tags

        text = f"{name} {description} {path.as_posix()}".lower()
        for category, keywords in _CATEGORY_RULES.items():
            hits = [word for word in keywords if word in text]
            if hits:
                return category, tuple(hits[:4])
        return "其他", ()

    def _load_index(self) -> dict[str, object]:
        if not self._index_path.exists():
            return {"category_overrides": {}}
        try:
            payload = json.loads(self._index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"category_overrides": {}}
        if not isinstance(payload, dict):
            return {"category_overrides": {}}
        if "category_overrides" not in payload or not isinstance(payload["category_overrides"], dict):
            payload["category_overrides"] = {}
        return payload

    def _save_index(self, payload: dict[str, object]) -> None:
        self._index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _unique_install_name(self, folder_name: str, skill_name: str) -> str:
        base = folder_name or skill_name
        candidate = _safe_folder_name(base)
        counter = 2
        while (self.skills_dir / candidate).exists() or (self.skills_dir / candidate).is_symlink():
            candidate = f"{_safe_folder_name(base)}-{counter}"
            counter += 1
        return candidate

    def _resolve_installed_folder(self, name: str) -> Path:
        direct = self.skills_dir / name
        if direct.exists() or direct.is_symlink():
            return direct
        for item in self.list_installed():
            if item.name == name:
                return Path(item.path)
        raise AgentError(f"未找到已安装技能：{name}")


def parse_skill_markdown(text: str) -> dict[str, str]:
    match = _FRONTMATTER.match(text)
    if not match:
        return {}
    block = match.group(1)
    result: dict[str, str] = {}
    for key, value in _SCALAR.findall(block):
        cleaned = value.strip().strip("'\"")
        if cleaned.startswith(">"):
            cleaned = cleaned.lstrip("> ").strip()
        result[key] = cleaned
    return result


def _iter_skill_files() -> list[Path]:
    files: list[Path] = []
    for root in AGENT_SCAN_ROOTS:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                name
                for name in dirnames
                if name not in SKIP_SCAN_DIRS and not name.startswith(".")
            ]
            if "SKILL.md" in filenames:
                files.append(Path(dirpath) / "SKILL.md")
    return files


def _classify_path(path: Path) -> tuple[str, str]:
    text = path.as_posix()
    home = Path.home().as_posix()
    if f"{home}/.hermes/" in text or text.startswith(f"{home}/.hermes"):
        return "hermes", "Hermes"
    if f"{home}/.cursor/" in text or text.startswith(f"{home}/.cursor"):
        return "cursor", "Cursor"
    if f"{home}/.claude/" in text or text.startswith(f"{home}/.claude"):
        return "claude", "Claude"
    if f"{home}/.agents/" in text or text.startswith(f"{home}/.agents"):
        return "agents", "Agents"
    return "other", "其他"


def _source_root(source_key: str) -> Path | None:
    mapping = {
        "hermes": Path.home() / ".hermes",
        "cursor": Path.home() / ".cursor",
        "claude": Path.home() / ".claude",
        "agents": Path.home() / ".agents",
    }
    return mapping.get(source_key)


def _is_allowed_source(path: Path) -> bool:
    resolved = path.resolve()
    for root in AGENT_SCAN_ROOTS:
        if not root.exists():
            continue
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _is_installed(name: str, folder_name: str, installed_keys: set[str]) -> bool:
    return name.lower() in installed_keys or folder_name.lower() in installed_keys


def _safe_folder_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\-.]+", "-", name.strip()).strip("-")
    return cleaned or "skill"
