"""Fast, deterministic lookup for third-party repo/project author metadata."""

from __future__ import annotations

import json
import re
from pathlib import Path

from secretary.agent.grounding import _extract_path_candidates
from secretary.agent.identity import is_author_request

_AUTHOR_MARKERS = re.compile(
    r"(作者|开发者|创建者|维护者|谁写|谁开发|谁做的|谁维护)",
    re.IGNORECASE,
)

_PROJECT_NAME_PATTERNS = (
    re.compile(
        r"(?:找|查|看|请问|帮我).{0,16}?"
        r"([A-Za-z0-9][\w./\s-]{1,48}?)\s*(?:项目|仓库|repo)?\s*的?\s*"
        r"(?:作者|开发者|创建者|维护者|谁写|谁开发)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^([A-Za-z0-9][\w./\s-]{1,48}?)\s*(?:项目|仓库|repo)?\s*的?\s*"
        r"(?:作者|开发者|创建者|维护者|谁写|谁开发)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(open\s*[-_]?\s*design)\b", re.IGNORECASE),
)


def is_project_author_question(message: str) -> bool:
    text = message.strip()
    if not text or is_author_request(text):
        return False
    if not _AUTHOR_MARKERS.search(text):
        return False
    if _extract_path_candidates(text):
        return True
    if any(pattern.search(text) for pattern in _PROJECT_NAME_PATTERNS):
        return True
    return bool(re.search(r"[A-Za-z0-9]{2,}", text))


def _slug_variants(raw: str) -> list[str]:
    name = raw.strip()
    if not name:
        return []
    lowered = name.lower()
    variants: list[str] = []
    for item in (name, lowered, lowered.replace(" ", "-"), lowered.replace(" ", "_"), lowered.replace(" ", "")):
        cleaned = item.strip(" ./")
        if cleaned and cleaned not in variants:
            variants.append(cleaned)
    return variants


def _project_name_candidates(message: str) -> list[str]:
    found: list[str] = []
    for pattern in _PROJECT_NAME_PATTERNS:
        match = pattern.search(message)
        if not match:
            continue
        raw = match.group(1).strip()
        found.extend(_slug_variants(raw))
    if re.search(r"\bopen\s*[-_]?\s*design\b", message, re.IGNORECASE):
        found.extend(_slug_variants("open-design"))
    deduped: list[str] = []
    for item in found:
        if item not in deduped:
            deduped.append(item)
    return deduped


def infer_project_root(message: str, working_dir: Path) -> Path | None:
    for token in _extract_path_candidates(message):
        try:
            path = Path(token).expanduser()
        except (OSError, ValueError):
            continue
        if path.is_dir():
            return path.resolve()
        if path.is_file() and path.parent.is_dir():
            return path.parent.resolve()

    search_roots: list[Path] = []
    wd = working_dir.expanduser()
    try:
        wd = wd.resolve()
    except OSError:
        wd = wd.expanduser()
    if wd.is_dir() and wd not in search_roots:
        search_roots.append(wd)
    parent = wd.parent
    if parent.is_dir() and parent not in search_roots:
        search_roots.append(parent)
    try:
        from secretary.config import settings
        projects_dir = Path(settings.projects_dir).expanduser()
    except Exception:
        projects_dir = Path.home() / "Documents" / "My Projects"

    for base in (
        projects_dir,
        Path.home() / "Projects",
        Path.home(),
    ):
        if base.is_dir():
            resolved = base.resolve()
            if resolved not in search_roots:
                search_roots.append(resolved)

    for name in _project_name_candidates(message):
        for root in search_roots:
            for slug in _slug_variants(name):
                candidate = root / slug
                if candidate.is_dir():
                    return candidate.resolve()
    return None


def _read_text(path: Path, *, limit: int = 12_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _package_author_fields(text: str) -> list[str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    lines: list[str] = []
    for key in ("author", "authors", "maintainers", "contributors"):
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            lines.append(f"- package.json `{key}`: {value.strip()}")
        elif isinstance(value, list) and value:
            preview = ", ".join(str(item) for item in value[:5])
            lines.append(f"- package.json `{key}`: {preview}")
        elif isinstance(value, dict) and value:
            lines.append(f"- package.json `{key}`: {json.dumps(value, ensure_ascii=False)}")
    return lines


def _readme_author_hints(text: str) -> list[str]:
    hints: list[str] = []
    patterns = (
        r"(?im)^\s*[*-]?\s*(?:author|authors|maintainer|维护者|作者)\s*[:：]\s*(.+)$",
        r"(?im)^\s*#\s*(?:author|authors|maintainer|维护者|作者)\s*[:：]?\s*(.+)$",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            line = match.group(1).strip()
            if line and line not in hints:
                hints.append(line)
    return hints[:5]


def lookup_project_author(message: str, working_dir: Path) -> str | None:
    root = infer_project_root(message, working_dir)
    if root is None:
        return None

    lines = [f"项目目录：`{root}`", ""]
    pkg = root / "package.json"
    if pkg.is_file():
        pkg_text = _read_text(pkg)
        author_fields = _package_author_fields(pkg_text)
        if author_fields:
            lines.append("在 package.json 中找到：")
            lines.extend(author_fields)
        else:
            lines.append(
                "package.json 存在，但无 `author` / `authors` / `maintainers` 字段（仅有 name、license 等元数据）。"
            )
    else:
        lines.append("根目录没有 package.json。")

    readme_path = next(
        (root / name for name in ("README.md", "README.zh-CN.md", "README") if (root / name).is_file()),
        None,
    )
    if readme_path is not None:
        readme_text = _read_text(readme_path)
        hints = _readme_author_hints(readme_text)
        if hints:
            lines.append("")
            lines.append(f"{readme_path.name} 中的作者/维护者线索：")
            lines.extend(f"- {hint}" for hint in hints)
        else:
            lines.append("")
            lines.append(f"{readme_path.name} 未写明本项目维护者/作者（仅有第三方 skill 归属等不算仓库作者）。")

    if len(lines) <= 2:
        return None

    lines.append("")
    lines.append(
        "结论：只能依据上述文件回答；若仍无作者字段，应说明「仓库元数据未标注作者」，不要猜测人名。"
    )
    return "\n".join(lines)
