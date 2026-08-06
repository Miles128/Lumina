"""Per-thread soft sandbox directories for default agent cwd."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


def sandbox_root(data_dir: Path) -> Path:
    return Path(data_dir).expanduser() / "sandbox"


def safe_thread_id(thread_id: str) -> str:
    raw = (thread_id or "").strip()
    if not raw:
        return "_default"
    cleaned = _SAFE_ID.sub("_", raw)
    return cleaned or "_default"


def _thread_dir(thread_id: str, data_dir: Path) -> Path:
    root = sandbox_root(data_dir).resolve()
    candidate = (root / safe_thread_id(thread_id)).resolve()
    if not candidate.is_relative_to(root):
        return root / "_default"
    return candidate


def ensure(thread_id: str, data_dir: Path) -> Path:
    path = _thread_dir(thread_id, data_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def remove(thread_id: str, data_dir: Path) -> None:
    path = _thread_dir(thread_id, data_dir)
    root = sandbox_root(data_dir).resolve()
    if not path.is_relative_to(root) or path == root:
        logger.warning("Refusing to remove sandbox path outside root: %s", path)
        return
    shutil.rmtree(path, ignore_errors=True)


def clear_all(data_dir: Path) -> int:
    """Remove every per-thread sandbox under {data_dir}/sandbox. Returns removed count."""
    root = sandbox_root(data_dir).resolve()
    removed = 0
    if not root.exists():
        return 0
    for child in root.iterdir():
        try:
            resolved = child.resolve()
        except OSError:
            continue
        if not resolved.is_relative_to(root) or resolved == root:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                continue
        removed += 1
    return removed
