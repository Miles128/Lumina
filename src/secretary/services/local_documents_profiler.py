"""Analyze local Documents for user portrait and memory indexing."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from secretary.config import Settings
from secretary.core.types import ConnectorHealth, ConnectorStatus, MemoryChunk, SourceKind
from secretary.exceptions import ConnectorError, ConnectorNotConfiguredError
from secretary.memory.ingest import chunk_text
from secretary.utils.paths import default_documents_dir

LOCALE_README = re.compile(r"^readme\.[a-z]{2}(?:-[a-z]{2})?\.md$", re.IGNORECASE)
READ_SUFFIXES = {".md", ".txt"}
SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    ".Trash",
    "Library",
    "__pycache__",
    "$RECYCLE.BIN",
    "vendor",
    "dist",
    "build",
    "target",
    ".venv",
    "venv",
    ".cursor",
    ".vscode",
    ".idea",
    "Pods",
    "DerivedData",
    "coverage",
    ".next",
    ".nuxt",
    "packages",
    "third_party",
    "external",
    "deps",
}
SKIP_PATH_SEGMENTS = {
    "node_modules",
    "src",
    "lib",
    "tests",
    "test",
    "scripts",
    "plugins",
    "examples",
    "vendor",
    "dist",
    "build",
    "target",
    "coverage",
    "packages",
    "third_party",
    "external",
    "github",
    "opensource",
    "open-source",
    "forks",
    "clones",
}
LOW_VALUE_PATH_SEGMENTS = {
    "projects",
    "dev",
    "development",
    "repos",
    "repository",
    "workspace",
    "code",
    "software",
    "sdk",
    "framework",
    "library",
    "templates",
    "starters",
}
PROJECT_MARKER_FILES = {
    "package.json",
    "pyproject.toml",
    "cargo.toml",
    "go.mod",
    "composer.json",
    "gemfile",
    "pnpm-lock.yaml",
    "package-lock.json",
    "setup.py",
    "tsconfig.json",
    "makefile",
    "dockerfile",
    ".gitignore",
    "pubspec.yaml",
    "build.gradle",
    "build.gradle.kts",
}
PROJECT_CHILD_DIRS = {"src", "lib", "tests", "test", "node_modules", "apps", "packages", "include"}
MIN_FILE_SCORE = 14
LOW_VALUE_DIR_PATTERN = re.compile(
    r"(^|[-_])(demo|starter|template|boilerplate|example|sample|tutorial|awesome|sdk|framework)[-_]",
    re.IGNORECASE,
)
TECH_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".swift",
    ".c",
    ".cpp",
    ".h",
    ".sql",
    ".sh",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".xml",
    ".lock",
    ".env",
    ".cfg",
    ".ini",
    ".gradle",
    ".wasm",
    ".bin",
    ".exe",
    ".dll",
    ".so",
    ".class",
    ".jar",
}
TECH_FILENAMES = {
    "package.json",
    "cargo.toml",
    "go.mod",
    "makefile",
    "dockerfile",
    "license",
    "changelog",
    "pnpm-lock.yaml",
    "package-lock.json",
}
NAME_SCORES: tuple[tuple[str, int], ...] = (
    ("readme", 4),
    ("简历", 22),
    ("resume", 22),
    ("cv", 18),
    ("个人介绍", 20),
    ("about", 14),
    ("bio", 14),
    ("随笔", 16),
    ("文章", 14),
    ("essay", 14),
    ("blog", 10),
    ("自我介绍", 20),
    ("日记", 16),
    ("周报", 14),
    ("月报", 14),
    ("总结", 12),
    ("规划", 12),
    ("目标", 12),
    ("想法", 12),
    ("笔记", 10),
    ("随记", 14),
    ("反思", 14),
    ("年度", 10),
    ("作品集", 16),
    ("portfolio", 16),
    ("个人", 12),
)
PERSONAL_FOLDER_PARTS = {
    "blog",
    "articles",
    "writing",
    "posts",
    "essays",
    "notes",
    "resume",
    "journal",
    "diary",
    "personal",
    "about-me",
    "随笔",
    "文章",
    "日记",
}
PERSONAL_CONTENT_MARKERS = (
    "关于我",
    "自我介绍",
    "工作经历",
    "个人简介",
    "我是",
    "我的",
    "擅长",
    "负责",
    "作品",
    "经历",
    "背景",
    "兴趣",
    "爱好",
    "目标",
    "规划",
    "about me",
    "my background",
    "work experience",
)
OSS_BOILERPLATE_MARKERS = (
    "## installation",
    "## contributing",
    "## license",
    "mit license",
    "apache license",
    "pull request",
    "npm install",
    "yarn install",
    "pnpm install",
    "git clone",
    "build status",
    "codecov",
    "getting started",
    "code of conduct",
    "contributors",
)
TECH_CONTENT_MARKERS = (
    "import ",
    "from ",
    "def ",
    "function ",
    "const ",
    "class ",
    "```python",
    "```javascript",
    "npm install",
    "pip install",
    "git clone",
    "public static void",
    "#include ",
)


class DocumentExcerpt(BaseModel):
    file: str
    preview: str


class LocalDocumentsProfile(BaseModel):
    generated_at: datetime
    analyzed_files: int = 0
    skipped_files: int = 0
    excerpts: list[DocumentExcerpt] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)

    def to_section_text(self) -> str:
        if not self.excerpts:
            return "未找到 README、简历或个人文章。请把相关文件放在 Documents 目录后重新分析。"
        lines = [
            f"已从 {len(self.excerpts)} 篇文档摘录原文。",
            "",
        ]
        for item in self.excerpts:
            preview = " ".join(item.preview.split())
            lines.append(f"### {item.file}")
            lines.append(preview[:480])
            lines.append("")
        return "\n".join(lines).strip()


@dataclass(frozen=True)
class _Candidate:
    path: Path
    relative: str
    score: int


class LocalDocumentsProfiler:
    """Scan Documents and infer user portrait without touching memory index."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def is_enabled(self) -> bool:
        return self._settings.local_documents_enabled

    def profile_path(self) -> Path:
        return self._settings.resolved_data_dir() / "local_documents_profile.json"

    def load_profile(self) -> LocalDocumentsProfile | None:
        path = self.profile_path()
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return LocalDocumentsProfile.model_validate(raw)

    def analyze_and_save(self) -> LocalDocumentsProfile:
        if not self._settings.local_documents_enabled:
            raise ConnectorNotConfiguredError("local documents analysis is disabled")

        root = self._resolve_root()
        if not root.exists() or not root.is_dir():
            raise ConnectorError(f"documents folder not found: {root}")

        candidates, skipped = self._select_files(root)
        excerpts: list[DocumentExcerpt] = []
        sources: list[str] = []
        for candidate in candidates:
            text = _read_text(candidate.path)
            if not text or _looks_technical(text) or not _is_relevant_to_user(text, candidate.path):
                skipped += 1
                continue
            preview = _preview_text(text)
            excerpts.append(DocumentExcerpt(file=candidate.relative, preview=preview))
            sources.append(candidate.relative)

        profile = LocalDocumentsProfile(
            generated_at=datetime.now(UTC),
            analyzed_files=len(excerpts),
            skipped_files=skipped,
            excerpts=excerpts,
            source_files=sources,
        )
        self.profile_path().write_text(
            profile.model_dump_json(indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return profile

    def memory_chunks(self, profile: LocalDocumentsProfile) -> list[MemoryChunk]:
        chunks: list[MemoryChunk] = []
        for excerpt in profile.excerpts:
            chunks.extend(
                chunk_text(
                    source=SourceKind.LOCAL_DOCUMENTS,
                    key=excerpt.file,
                    title=f"本地文档 · {Path(excerpt.file).name}",
                    body=excerpt.preview,
                    metadata={"path": excerpt.file, "kind": "local_document"},
                )
            )
        return chunks

    def _resolve_root(self) -> Path:
        custom = self._settings.local_documents_path.strip()
        if custom:
            return Path(custom).expanduser()
        return default_documents_dir()

    def _select_files(self, root: Path) -> tuple[list[_Candidate], int]:
        scored: list[_Candidate] = []
        skipped = 0
        seen = 0
        max_walk = min(max(self._settings.local_documents_max_files * 5, 300), 4000)
        max_analyze = min(self._settings.local_documents_max_files, 25)

        for path in _walk_files(root, max_walk):
            seen += 1
            if path.suffix.lower() in TECH_EXTENSIONS:
                skipped += 1
                continue
            if path.name.lower() in TECH_FILENAMES:
                skipped += 1
                continue
            if path.suffix.lower() not in READ_SUFFIXES:
                skipped += 1
                continue
            score = _score_file(path)
            if score < MIN_FILE_SCORE:
                skipped += 1
                continue
            relative = _safe_relative(path, root)
            scored.append(_Candidate(path=path, relative=relative, score=score))

        scored.sort(key=lambda item: item.score, reverse=True)
        selected = scored[:max_analyze]
        skipped += max(0, len(scored) - len(selected))
        skipped += max(0, seen - len(scored) - skipped)
        return selected, skipped


def _score_file(path: Path) -> int:
    name = path.name.lower()
    if LOCALE_README.match(name):
        return 0
    if _looks_like_project_root(path.parent):
        if name == "readme.md" or name.startswith("readme"):
            return 0
        score = 0
    else:
        score = 0
    for token, points in NAME_SCORES:
        if token in name:
            score += points
    parts = {part.lower() for part in path.parts}
    if parts & PERSONAL_FOLDER_PARTS:
        score += 10
    if parts & SKIP_PATH_SEGMENTS:
        score -= 20
    if parts & LOW_VALUE_PATH_SEGMENTS:
        score -= 8
    if any(LOW_VALUE_DIR_PATTERN.search(part) for part in path.parts):
        score -= 12
    parent_name = path.parent.name.lower()
    if any(
        token in parent_name
        for token in ("blog", "writing", "resume", "portfolio", "about", "personal", "journal", "随笔", "文章", "日记")
    ):
        score += 12
    if any("\u4e00" <= char <= "\u9fff" for char in path.stem):
        if "readme" not in name:
            score += 14
    return score


def _looks_like_project_root(directory: Path) -> bool:
    try:
        for child in directory.iterdir():
            if child.name.lower() in PROJECT_MARKER_FILES:
                return True
            if child.is_dir() and child.name.lower() in PROJECT_CHILD_DIRS:
                return True
    except OSError:
        return False
    return False


def _is_relevant_to_user(text: str, path: Path) -> bool:
    name = path.name.lower()
    strong_name_tokens = (
        "简历",
        "resume",
        "cv",
        "个人介绍",
        "自我介绍",
        "about",
        "bio",
        "portfolio",
        "作品集",
    )
    if any(token in name for token in strong_name_tokens):
        return True

    sample = text[:4000].lower()
    personal_hits = sum(1 for marker in PERSONAL_CONTENT_MARKERS if marker.lower() in sample)
    oss_hits = sum(1 for marker in OSS_BOILERPLATE_MARKERS if marker in sample)
    if oss_hits >= 2 and personal_hits == 0:
        return False
    if personal_hits >= 1:
        return True

    parts = {part.lower() for part in path.parts}
    if parts & PERSONAL_FOLDER_PARTS:
        return len(text.strip()) > 80 and oss_hits <= 1

    if any("\u4e00" <= char <= "\u9fff" for char in path.stem) and "readme" not in name:
        return oss_hits == 0

    return False


def _looks_technical(text: str) -> bool:
    sample = text[:8000]
    hits = sum(1 for marker in TECH_CONTENT_MARKERS if marker in sample)
    if hits >= 3:
        return True
    code_fence_count = sample.count("```")
    if code_fence_count >= 4:
        return True
    return False


def _read_text(path: Path, max_bytes: int = 48_000) -> str:
    data = path.read_bytes()[:max_bytes]
    return data.decode("utf-8", errors="replace").strip()


def _preview_text(text: str, max_len: int = 320) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def _walk_files(root: Path, max_files: int) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in SKIP_DIR_NAMES
            and not name.startswith(".")
            and not LOW_VALUE_DIR_PATTERN.search(name)
        ]
        for name in filenames:
            if name.startswith("."):
                continue
            files.append(Path(dirpath) / name)
            if len(files) >= max_files:
                return files
    return files


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


class LocalDocumentsPlatform:
    """Settings gate for local Documents portrait analysis."""

    source = SourceKind.LOCAL_DOCUMENTS

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._profiler = LocalDocumentsProfiler(settings)

    def is_configured(self) -> bool:
        return self._profiler.is_enabled()

    def health_from_store(self, stored: ConnectorHealth | None) -> ConnectorHealth:
        if not self.is_configured():
            return ConnectorHealth(
                source=SourceKind.LOCAL_DOCUMENTS,
                status=ConnectorStatus.NOT_CONFIGURED,
                message="未启用",
            )
        if stored:
            return stored
        saved = self._profiler.load_profile()
        if saved and saved.analyzed_files > 0:
            return ConnectorHealth(
                source=SourceKind.LOCAL_DOCUMENTS,
                status=ConnectorStatus.READY,
                message=f"已摘录 {saved.analyzed_files} 篇文档用于画像",
                item_count=saved.analyzed_files,
            )
        return ConnectorHealth(
            source=SourceKind.LOCAL_DOCUMENTS,
            status=ConnectorStatus.NOT_CONFIGURED,
            message="已启用，点击测试连接开始分析",
        )
