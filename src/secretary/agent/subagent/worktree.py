"""Git worktree isolation for worker sub-agents."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def find_git_root(path: Path) -> Path | None:
    """Return the git repository root containing ``path``, or None."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("git root lookup failed for %s: %s", path, exc)
        return None
    if completed.returncode != 0:
        return None
    root = completed.stdout.strip()
    return Path(root).resolve() if root else None


def create_worktree(repo_root: Path, run_id: str, *, base_dir: Path | None = None) -> Path | None:
    """Create a detached worktree under ``base_dir`` / ``run_id``.

    Returns the worktree path on success, or None on failure.
    """
    root = repo_root.resolve()
    if find_git_root(root) is None:
        return None
    parent = (base_dir or (Path.home() / ".lumina" / "worktrees")).expanduser()
    parent.mkdir(parents=True, exist_ok=True)
    worktree_path = parent / f"wt-{run_id}"
    if worktree_path.exists():
        shutil.rmtree(worktree_path, ignore_errors=True)
    branch = f"lumina/wt-{run_id}"
    try:
        # Prefer a new branch from HEAD so workers can commit locally without touching main.
        add = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "worktree",
                "add",
                "-b",
                branch,
                str(worktree_path),
                "HEAD",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if add.returncode != 0:
            logger.warning(
                "git worktree add failed: %s",
                (add.stderr or add.stdout or "").strip()[:300],
            )
            return None
        return worktree_path.resolve()
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("create_worktree failed: %s", exc)
        return None


def diff_stat(worktree: Path) -> str:
    """Return ``git diff --stat`` for the worktree (including untracked via status)."""
    try:
        diff = subprocess.run(
            ["git", "-C", str(worktree), "diff", "--stat", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        status = subprocess.run(
            ["git", "-C", str(worktree), "status", "--short"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"(diff unavailable: {exc})"
    parts: list[str] = []
    if diff.returncode == 0 and diff.stdout.strip():
        parts.append(diff.stdout.strip())
    if status.returncode == 0 and status.stdout.strip():
        parts.append("status:\n" + status.stdout.strip())
    return "\n".join(parts) if parts else "(no local changes)"


def cleanup_worktree(
    repo_root: Path,
    worktree: Path,
    *,
    remove_branch: bool = True,
) -> None:
    """Best-effort remove a Lumina-managed worktree."""
    run_id = worktree.name.removeprefix("wt-")
    branch = f"lumina/wt-{run_id}"
    try:
        subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(worktree)],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("worktree remove failed: %s", exc)
        shutil.rmtree(worktree, ignore_errors=True)
    if remove_branch:
        try:
            subprocess.run(
                ["git", "-C", str(repo_root), "branch", "-D", branch],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
