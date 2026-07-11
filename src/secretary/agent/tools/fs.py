"""File-system tools: list_dir, file_read, file_write, file_delete."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any

from secretary.agent.tools.base import Tool, ToolResult, _resolve_path

READABLE_MAX_BYTES = 2 * 1024 * 1024

# 敏感路径模式：写入这些路径需要额外警告（不阻止，因已有 needs_confirmation 保护）
_SENSITIVE_PATH_PATTERNS = (
    ".ssh",
    ".gnupg",
    ".aws",
    ".docker",
    ".bashrc",
    ".bash_profile",
    ".zshrc",
    ".profile",
    ".gitconfig",
    ".env",
    ".npmrc",
    ".pypirc",
)


def _sensitive_path_warning(path: Path) -> str | None:
    """检查路径是否敏感，返回警告字符串（如敏感）或 None。

    不阻止写入，仅附加警告提醒用户。已有 needs_confirmation=True 保护。
    """
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path
    str_path = str(resolved)
    # 系统目录
    if str_path.startswith("/etc/") or str_path == "/etc":
        return f"⚠️ 警告：写入系统目录 {path}，请格外谨慎。"
    # home 下的敏感文件/目录
    for pattern in _SENSITIVE_PATH_PATTERNS:
        if pattern in str_path:
            return f"⚠️ 警告：写入敏感路径 {path}（匹配 {pattern}），请确认操作意图。"
    return None


def _human_size(size: int) -> str:
    value: float = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


class ListDirTool(Tool):
    name = "list_dir"
    description = "List files and directories in a given path. Returns names, types, and sizes."
    needs_confirmation = False
    risk_level = "low"
    read_only = True

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list (default: current dir)"},
                "recursive": {"type": "boolean", "description": "List recursively (default: false, max depth 3)"},
                "pattern": {"type": "string", "description": "Glob pattern to filter (e.g. '*.py', '*.md')"},
            },
            "required": [],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        raw_path = arguments.get("path", ".")
        path = Path(raw_path)
        if not path.is_absolute():
            path = working_dir / path
        path = path.resolve()

        if not path.exists():
            return ToolResult.failure(
                f"Error: path not found: {path}",
                error_type="not_found",
                retryable=False,
            )
        if not path.is_dir():
            return ToolResult.failure(
                f"Error: not a directory: {path}",
                error_type="not_found",
                retryable=False,
            )

        recursive = arguments.get("recursive", False)
        pattern = str(arguments.get("pattern", "*") or "*")

        def _matches(name: str, *, is_dir: bool) -> bool:
            if pattern in ("", "*"):
                return True
            if is_dir:
                return fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(name, pattern.rstrip("/"))
            return fnmatch.fnmatch(name, pattern)

        lines: list[str] = []
        try:
            if recursive:
                max_depth = 3
                for root, dirs, files in os.walk(path):
                    rel = Path(root).relative_to(path)
                    depth = len(rel.parts)
                    if depth >= max_depth:
                        dirs.clear()
                        continue
                    for d in sorted(dirs):
                        if not _matches(d, is_dir=True):
                            continue
                        lines.append(f"  {'  ' * depth}📁 {d}/")
                    for f in sorted(files):
                        if not _matches(f, is_dir=False):
                            continue
                        fp = Path(root) / f
                        try:
                            size_str = _human_size(fp.stat().st_size)
                        except OSError:
                            size_str = "?"
                        lines.append(f"  {'  ' * depth}📄 {f}  ({size_str})")
                    if len(lines) > 200:
                        lines.append("  ... (truncated, >200 entries)")
                        break
            else:
                entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
                ext_counts: dict[str, int] = {}
                for entry in entries:
                    if entry.is_dir():
                        if not _matches(entry.name, is_dir=True):
                            continue
                        try:
                            count = sum(1 for _ in entry.iterdir())
                            lines.append(f"📁 {entry.name}/  ({count} items)")
                        except PermissionError:
                            lines.append(f"📁 {entry.name}/  (子项不可列)")
                        except OSError:
                            lines.append(f"📁 {entry.name}/")
                    else:
                        if not _matches(entry.name, is_dir=False):
                            continue
                        try:
                            size = entry.stat().st_size
                            lines.append(f"📄 {entry.name}  ({_human_size(size)})")
                        except OSError:
                            lines.append(f"📄 {entry.name}")
                        suffix = entry.suffix.lower() or "(no_ext)"
                        ext_counts[suffix] = ext_counts.get(suffix, 0) + 1
                    if len(lines) > 100:
                        lines.append("... (truncated, >100 entries)")
                        break
                if ext_counts:
                    parts = [f"{ext}={count}" for ext, count in sorted(ext_counts.items())]
                    lines.insert(0, f"扩展名统计: {', '.join(parts)}")
        except PermissionError:
            return ToolResult.failure(
                f"Error: permission denied: {path}",
                error_type="permission",
                retryable=False,
            )
        except Exception as exc:
            return ToolResult.failure(
                f"Error listing directory: {exc}",
                error_type="internal",
                retryable=False,
            )

        header = f"📂 {path} ({len(lines)} entries)"
        footer = (
            "注：📁/📄 行是真实目录项名称，可直接用于回答「有哪些文件夹/项目」。"
            "需要文件内容时用 file_read；按关键词找目录/文件用 search_files。"
            "不要对用户声称灵犀「没有读权限」或「只能看目录结构」。"
        )
        return f"{header}\n" + "\n".join(lines) + f"\n\n{footer}"

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        path = _resolve_path(str(arguments.get("path", ".")), working_dir)
        return f"📂 列出目录 `{path}`"


class FileReadTool(Tool):
    name = "file_read"
    description = "Read the contents of a file. No confirmation needed for reading."
    needs_confirmation = False
    risk_level = "low"
    read_only = True

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "offset": {"type": "integer", "description": "Line offset (1-based)"},
                "limit": {"type": "integer", "description": "Max lines to read (default 200)"},
                "encoding": {"type": "string", "description": "File encoding (default utf-8)"},
            },
            "required": ["path"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        path = Path(arguments.get("path", ""))
        if not path.is_absolute():
            path = working_dir / path
        path = path.resolve()

        if not path.exists():
            return ToolResult.failure(
                f"Error: file not found: {path}",
                error_type="not_found",
                retryable=False,
            )
        if not path.is_file():
            return ToolResult.failure(
                f"Error: not a file: {path}",
                error_type="not_found",
                retryable=False,
            )

        # 参数类型校验：LLM 可能传入字符串形式的整数（如 "5"），需显式转换
        try:
            offset = max(1, int(arguments.get("offset", 1))) - 1
            limit = int(arguments.get("limit", 200))
        except (TypeError, ValueError):
            return ToolResult.failure(
                "Error: offset/limit must be integers",
                error_type="validation",
                retryable=False,
            )

        try:
            file_size = path.stat().st_size
            if file_size > READABLE_MAX_BYTES:
                return ToolResult.failure(
                    f"Error: file too large ({_human_size(file_size)}), max {_human_size(READABLE_MAX_BYTES)}",
                    error_type="validation",
                    retryable=False,
                )

            encoding = arguments.get("encoding", "utf-8")
            content = path.read_text(encoding=encoding, errors="replace")
            lines = content.splitlines()
            selected = lines[offset : offset + limit]
            total_lines = len(lines)
            header = f"📄 {path} ({total_lines} lines, {_human_size(file_size)})"
            body = "\n".join(f"{i + offset + 1}: {line}" for i, line in enumerate(selected))
            if offset + limit < total_lines:
                body += f"\n... ({total_lines - offset - limit} more lines)"
            return f"{header}\n{body}"
        except PermissionError:
            return ToolResult.failure(
                f"Error: permission denied: {path}",
                error_type="permission",
                retryable=False,
            )
        except Exception as exc:
            return ToolResult.failure(
                f"Error reading file: {exc}",
                error_type="internal",
                retryable=False,
            )

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        return f"📖 读取文件 `{path}`"


class FileWriteTool(Tool):
    name = "file_write"
    description = "Write content to a file. REQUIRES user confirmation before executing."
    needs_confirmation = True
    risk_level = "medium"
    read_only = False

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
                "append": {"type": "boolean", "description": "Append instead of overwrite (default false)"},
            },
            "required": ["path", "content"],
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        path = Path(arguments.get("path", ""))
        if not path.is_absolute():
            path = working_dir / path
        content = arguments.get("content", "")
        append = arguments.get("append", False)
        action = "追加" if append else "写入"
        exists = path.exists()
        size_info = f" ({len(content)} 字符)"
        if exists:
            return f"📝 {action}文件 `{path}`（文件已存在，将被{'追加' if append else '覆盖'}）{size_info}"
        return f"📝 {action}新文件 `{path}`{size_info}"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        path = Path(arguments.get("path", ""))
        if not path.is_absolute():
            path = working_dir / path
        # 确保内容为字符串：LLM 可能传入非字符串值
        content_raw = arguments.get("content", "")
        content = content_raw if isinstance(content_raw, str) else str(content_raw)
        append = arguments.get("append", False)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if append:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(content)
            else:
                path.write_text(content, encoding="utf-8")
            result = f"OK: wrote {len(content)} chars to {path}"
            # 敏感路径附加警告（不阻止写入，因已有 needs_confirmation 保护）
            warning = _sensitive_path_warning(path)
            if warning:
                result = f"{warning}\n{result}"
            return result
        except PermissionError:
            return ToolResult.failure(
                f"Error: permission denied: {path}",
                error_type="permission",
                retryable=False,
            )
        except Exception as exc:
            return ToolResult.failure(
                f"Error writing file: {exc}",
                error_type="internal",
                retryable=False,
            )


class FileDeleteTool(Tool):
    name = "file_delete"
    description = "Delete a file. Always requires user confirmation before executing."
    needs_confirmation = True
    risk_level = "high"
    read_only = False

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to delete"},
            },
            "required": ["path"],
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        return f"🗑️ 删除文件 `{path}`"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        if not path.exists():
            return ToolResult.failure(
                f"Error: file not found: {path}",
                error_type="not_found",
                retryable=False,
            )
        if not path.is_file():
            return ToolResult.failure(
                f"Error: not a file: {path}",
                error_type="not_found",
                retryable=False,
            )
        try:
            path.unlink()
            return f"OK: deleted {path}"
        except PermissionError:
            return ToolResult.failure(
                f"Error: permission denied: {path}",
                error_type="permission",
                retryable=False,
            )
        except Exception as exc:
            return ToolResult.failure(
                f"Error deleting file: {exc}",
                error_type="internal",
                retryable=False,
            )
