"""Hard write jail for the turn working_dir (thread sandbox or selected workspace).

When ``full_fs_access`` is False, write/edit/move/delete targets and shell absolute
paths must stay under the active working_dir. Reads are unrestricted.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path

_full_fs_access: ContextVar[bool] = ContextVar("lumina_full_fs_access", default=False)

# Absolute paths and ~/... tokens in shell commands.
_ABS_PATH_RE = re.compile(
    r"(?:(?<=\s)|^|[=:'\"])"
    r"("
    r"~(?:/[^\s'\"`;|&><]*)?"
    r"|/(?:Users|home|tmp|var|etc|opt|private)[^\s'\"`;|&><]*"
    r"|/[A-Za-z0-9._+-][^\s'\"`;|&><]*"
    r")"
)


class FsJailError(PermissionError):
    """Raised when a write targets a path outside the active working_dir."""


def get_full_fs_access() -> bool:
    return bool(_full_fs_access.get())


def set_full_fs_access(enabled: bool) -> Token[bool]:
    return _full_fs_access.set(bool(enabled))


def reset_full_fs_access(token: Token[bool]) -> None:
    _full_fs_access.reset(token)


@contextmanager
def full_fs_access_scope(enabled: bool) -> Iterator[None]:
    token = set_full_fs_access(enabled)
    try:
        yield
    finally:
        reset_full_fs_access(token)


def writable_root(working_dir: Path) -> Path:
    return Path(working_dir).expanduser().resolve()


def is_writable_path(path: Path, working_dir: Path, *, full_fs_access: bool | None = None) -> bool:
    if full_fs_access is None:
        full_fs_access = get_full_fs_access()
    if full_fs_access:
        return True
    try:
        resolved = Path(path).expanduser().resolve()
        root = writable_root(working_dir)
        return resolved.is_relative_to(root)
    except (OSError, ValueError):
        return False


def assert_writable(
    path: Path,
    working_dir: Path,
    *,
    full_fs_access: bool | None = None,
) -> Path:
    """Return resolved path, or raise FsJailError when outside the jail."""
    if full_fs_access is None:
        full_fs_access = get_full_fs_access()
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError as exc:
        raise FsJailError(f"sandbox: cannot resolve path: {path}") from exc
    if full_fs_access:
        return resolved
    root = writable_root(working_dir)
    if not resolved.is_relative_to(root):
        raise FsJailError(
            f"sandbox: cannot write outside working directory `{root}`: {resolved}. "
            "Enable「完全权限」to allow paths outside the current workspace/sandbox."
        )
    return resolved


def _candidate_shell_paths(command: str) -> list[str]:
    found: list[str] = []
    for match in _ABS_PATH_RE.finditer(command or ""):
        raw = match.group(1).rstrip(")]},.")
        if not raw or raw in {"/", "~"}:
            continue
        # Skip flags that look like paths (/dev/null is still a path — allowlist later).
        found.append(raw)
    return found


def shell_escapes_jail(
    command: str,
    working_dir: Path,
    *,
    full_fs_access: bool | None = None,
) -> str | None:
    """Return an error message if the command references absolute paths outside the jail.

    Relative paths are allowed (they resolve under cwd). Read-only redirects to
    common device paths are ignored.
    """
    if full_fs_access is None:
        full_fs_access = get_full_fs_access()
    if full_fs_access:
        return None
    root = writable_root(working_dir)
    allow_exact = {
        Path("/dev/null").resolve(),
        Path("/dev/stdin").resolve(),
        Path("/dev/stdout").resolve(),
        Path("/dev/stderr").resolve(),
    }
    for raw in _candidate_shell_paths(command):
        try:
            resolved = Path(raw).expanduser().resolve()
        except OSError:
            continue
        if resolved in allow_exact:
            continue
        if resolved.is_relative_to(root):
            continue
        return (
            f"sandbox: shell command references path outside working directory "
            f"`{root}`: {resolved}. Enable「完全权限」or use relative paths."
        )
    return None
