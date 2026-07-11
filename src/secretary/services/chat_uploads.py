"""Persist chat attachments under data_dir/uploads/{thread_id}/."""

from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_UPLOAD_FILES = 10

DEFAULT_ATTACHMENT_PROMPT = "请阅读附件并用 read_document / file_read 总结要点。"

_SAFE_NAME = re.compile(r"[^\w.\-()\u4e00-\u9fff]+", re.UNICODE)


@dataclass(frozen=True)
class SavedUpload:
    name: str
    path: str
    size: int

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "path": self.path, "size": self.size}


def _safe_filename(name: str) -> str:
    base = Path(name or "file").name.strip() or "file"
    cleaned = _SAFE_NAME.sub("_", base).strip("._") or "file"
    return cleaned[:180]


def uploads_root(data_dir: Path) -> Path:
    return data_dir / "uploads"


def thread_upload_dir(data_dir: Path, thread_id: str) -> Path:
    tid = (thread_id or "default").strip() or "default"
    # Keep path segment safe
    tid = re.sub(r"[^\w\-]", "_", tid)[:64] or "default"
    path = uploads_root(data_dir) / tid
    path.mkdir(parents=True, exist_ok=True)
    return path


def _check_size(size: int) -> None:
    if size > MAX_UPLOAD_BYTES:
        raise ValueError(f"file too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")


def _unique_dest(dest_dir: Path, filename: str) -> tuple[str, Path]:
    safe = _safe_filename(filename)
    unique = f"{uuid.uuid4().hex[:8]}_{safe}"
    return safe, dest_dir / unique


def save_upload_bytes(
    data_dir: Path,
    *,
    thread_id: str,
    filename: str,
    content: bytes,
) -> SavedUpload:
    _check_size(len(content))
    dest_dir = thread_upload_dir(data_dir, thread_id)
    safe, dest = _unique_dest(dest_dir, filename)
    dest.write_bytes(content)
    return SavedUpload(name=safe, path=str(dest.resolve()), size=len(content))


def copy_local_path(
    data_dir: Path,
    *,
    thread_id: str,
    source: str | Path,
) -> SavedUpload:
    src = Path(source).expanduser().resolve()
    if not src.is_file():
        raise ValueError(f"not a file: {src}")
    size = src.stat().st_size
    _check_size(size)
    dest_dir = thread_upload_dir(data_dir, thread_id)
    safe, dest = _unique_dest(dest_dir, src.name)
    shutil.copy2(src, dest)
    return SavedUpload(name=safe, path=str(dest.resolve()), size=size)


def format_attachments_block(paths: list[str]) -> str:
    """User-visible context block listing absolute attachment paths for the agent."""
    lines: list[str] = []
    for raw in paths:
        path = Path(str(raw)).expanduser()
        if not path.exists():
            continue
        resolved = str(path.resolve())
        lines.append(f"- {path.name}: `{resolved}`")
    if not lines:
        return ""
    return (
        "## 附件\n"
        "用户上传了以下文件（绝对路径）。请用 `read_document`（xlsx/pdf/docx）"
        "或 `file_read`（文本）读取内容后再回答。\n"
        + "\n".join(lines)
    )
