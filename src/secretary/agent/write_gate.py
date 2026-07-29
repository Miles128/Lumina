"""WriteGate — isolate subagent drafts under proposals/; business writes need landing roles.

FR-53: children (explore/worker/pro/con/…) may only write under proposals roots.
Landing roles (root / referee) may write business paths when the gate is unlocked
(after HITL confirm). When no spawn context is active, behavior stays open (root).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

WriteRole = Literal[
    "root",
    "plan",
    "explore",
    "worker",
    "pro",
    "con",
    "referee",
    "write_gate",
]

LANDING_ROLES = frozenset({"root", "referee", "write_gate"})
DISPLAY_NAMES: dict[str, str] = {
    "root": "项目主管",
    "plan": "产品经理",
    "explore": "调研分析",
    "worker": "执行者",
    "pro": "方案主张",
    "con": "风险质询",
    "referee": "评审仲裁",
    "write_gate": "项目落地",
}


class WriteGateError(PermissionError):
    """Raised when a write targets a path forbidden for the active role."""


@dataclass(frozen=True, slots=True)
class WriteGateContext:
    role: str = "root"
    run_id: str | None = None
    workspace: Path | None = None
    unlocked: bool = True  # landing roles only; ignored for jailed roles


_CTX: ContextVar[WriteGateContext | None] = ContextVar("lumina_write_gate", default=None)


def get_write_gate() -> WriteGateContext:
    return _CTX.get() or WriteGateContext()


def display_name_for_role(role: str) -> str:
    return DISPLAY_NAMES.get(role, role)


def proposals_root(*, run_id: str, workspace: Path | None) -> Path:
    """Prefer workspace `.lumina/proposals/{run_id}`; fall back to ~/.lumina/proposals."""
    rid = (run_id or "anon").strip() or "anon"
    if workspace is not None:
        return (workspace / ".lumina" / "proposals" / rid).resolve()
    return (Path.home() / ".lumina" / "proposals" / rid).resolve()


def is_proposals_path(path: Path, *, run_id: str, workspace: Path | None) -> bool:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path
    root = proposals_root(run_id=run_id, workspace=workspace)
    try:
        resolved.relative_to(root)
        return True
    except ValueError:
        return False


def assert_write_allowed(path: Path, *, ctx: WriteGateContext | None = None) -> None:
    """Allow write or raise WriteGateError."""
    gate = ctx if ctx is not None else get_write_gate()
    role = (gate.role or "root").strip() or "root"

    # No active jail: primary agent / unspecified → open (legacy behavior).
    if gate.run_id is None and role == "root":
        return

    try:
        resolved = path.expanduser().resolve()
    except OSError as exc:
        raise WriteGateError(f"WriteGate: cannot resolve path {path}: {exc}") from exc

    if role in LANDING_ROLES:
        if gate.unlocked:
            return
        # Locked landing role may still write drafts.
        if gate.run_id and is_proposals_path(
            resolved, run_id=gate.run_id, workspace=gate.workspace
        ):
            return
        raise WriteGateError(
            "WriteGate: 项目落地闸门已锁定；业务路径写入需评审仲裁收尾并确认。"
        )

    # Jailed roles: proposals only.
    if not gate.run_id:
        raise WriteGateError(
            f"WriteGate: 角色 {display_name_for_role(role)} 缺少 run_id，禁止写盘。"
        )
    if is_proposals_path(resolved, run_id=gate.run_id, workspace=gate.workspace):
        return
    root = proposals_root(run_id=gate.run_id, workspace=gate.workspace)
    raise WriteGateError(
        f"WriteGate: {display_name_for_role(role)} 只能写入草稿目录 `{root}`，"
        f"不能直接改业务路径 `{resolved}`。请把提案写到 proposals，由项目落地收尾。"
    )


@contextmanager
def write_gate_scope(
    *,
    role: str,
    run_id: str | None,
    workspace: Path | None = None,
    unlocked: bool = False,
) -> Iterator[WriteGateContext]:
    """Bind WriteGate for the duration of a subagent / debate / landing phase."""
    bound = WriteGateContext(
        role=role,
        run_id=run_id,
        workspace=workspace.resolve() if workspace is not None else None,
        unlocked=unlocked,
    )
    token: Token[WriteGateContext | None] = _CTX.set(bound)
    try:
        yield bound
    finally:
        _CTX.reset(token)
