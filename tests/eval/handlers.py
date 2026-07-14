"""Eval case handlers (deterministic, no live LLM)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from secretary.agent.agent_profile import AgentProfile
from secretary.agent.context_compaction import compact_messages_if_needed
from secretary.agent.hook_policies import CommandDenyHook, HooksConfig, PathAllowlistHook
from secretary.agent.lifecycle_hooks import ToolExecContext
from secretary.agent.p0_tools import AskUserTool, is_user_input_request
from secretary.agent.permission_guard import guard_tools_for_profile
from secretary.agent.stop_hooks import LoopSnapshot
from secretary.agent.structured_cards import EmitCardTool, is_structured_card_output
from secretary.agent.subagent.archetype_router import select_archetype
from secretary.agent.subagent.worktree import create_worktree, diff_stat, find_git_root
from secretary.agent.tools.base import Tool
from secretary.agent.tools.fs import FileWriteTool
from secretary.agent.tools.shell import ShellTool

from .harness import EvalCase, register_handler


class _NamedTool(Tool):
    def __init__(self, name: str, *, needs_confirmation: bool = False) -> None:
        self.name = name
        self.needs_confirmation = needs_confirmation
        self.description = name
        self.risk_level = "low"
        self.read_only = not needs_confirmation

    def _parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def execute(self, arguments: dict, working_dir: Path) -> str:
        del arguments, working_dir
        return "ok"


@register_handler("ask_user_short_circuit")
def handle_ask_user(case: EvalCase) -> None:
    tool = AskUserTool()
    out = tool.execute(
        {
            "context": "pick",
            "questions": [{"id": "q1", "prompt": "Continue?", "options": ["yes", "no"]}],
        },
        Path("."),
    )
    assert is_user_input_request(out)
    assert "ASK_USER_REQUEST" in out
    payload = case.payload.get("expect_contains") or []
    for fragment in payload:
        assert fragment in out


@register_handler("plan_permission_guard")
def handle_plan_guard(case: EvalCase) -> None:
    tools = [
        _NamedTool("file_read"),
        _NamedTool("file_write", needs_confirmation=True),
        ShellTool(),
        FileWriteTool(),
    ]
    guarded = guard_tools_for_profile(AgentProfile.PLAN, tools)
    names = {tool.name for tool in guarded}
    assert "file_read" in names
    assert "file_write" not in names
    assert "shell" not in names


@register_handler("compaction_retains_facts")
def handle_compaction(case: EvalCase) -> None:
    must_keep = case.payload.get("must_keep") or []
    messages = [{"role": "system", "content": "sys"}]
    # Seed a distinctive fact early, then pad history.
    messages.append(
        {
            "role": "user",
            "content": "Important path is /tmp/lumina-eval-secret.txt and conclusion=PASS_EVAL",
        }
    )
    messages.append({"role": "assistant", "content": "Noted the secret path and PASS_EVAL."})
    for index in range(24):
        messages.append({"role": "user", "content": f"noise {index} " + ("x" * 900)})
        messages.append({"role": "assistant", "content": f"ack {index} " + ("y" * 900)})
    result = compact_messages_if_needed(messages, None, max_tokens=6000, keep_tail=4)
    assert result.triggered is True
    blob = json.dumps(result.messages, ensure_ascii=False)
    for fact in must_keep:
        assert fact in blob, f"missing fact after compaction: {fact}"


@register_handler("archetype_router")
def handle_archetype(case: EvalCase) -> None:
    for item in case.payload.get("cases") or []:
        got = select_archetype(
            str(item.get("goal", "")),
            explicit=item.get("explicit"),
            success_criteria=str(item.get("success_criteria", "")),
        )
        assert got == item["expect"], f"{item} -> {got}"


@register_handler("worker_worktree_isolation")
def handle_worktree(case: EvalCase) -> None:
    """Placeholder — real isolation check runs in test_eval_cases with tmp_path."""
    del case
    assert callable(create_worktree)
    assert callable(find_git_root)
    assert callable(diff_stat)


def assert_worker_worktree_isolation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "eval@lumina.test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Eval"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    assert find_git_root(repo) == repo.resolve()
    wt_a = create_worktree(repo, "eval-a", base_dir=tmp_path / "wts")
    wt_b = create_worktree(repo, "eval-b", base_dir=tmp_path / "wts")
    assert wt_a is not None and wt_b is not None
    (wt_a / "a.txt").write_text("A", encoding="utf-8")
    (wt_b / "b.txt").write_text("B", encoding="utf-8")
    assert not (wt_a / "b.txt").exists()
    assert not (wt_b / "a.txt").exists()
    assert (wt_a / "a.txt").read_text(encoding="utf-8") == "A"
    assert (wt_b / "b.txt").read_text(encoding="utf-8") == "B"


@register_handler("hooks_command_deny")
def handle_hooks_deny(case: EvalCase) -> None:
    del case
    hook = CommandDenyHook(deny_substrings=("sudo ", "rm -rf /"))
    snap = LoopSnapshot(iteration=0, max_iterations=5, latest_user_message="")
    denied = hook.before_tool_execution(
        ToolExecContext(
            snapshot=snap,
            tool_name="shell",
            arguments={"command": "sudo reboot"},
            working_dir=Path("."),
        )
    )
    assert denied.should_skip is True
    allowed = hook.before_tool_execution(
        ToolExecContext(
            snapshot=snap,
            tool_name="shell",
            arguments={"command": "ls"},
            working_dir=Path("."),
        )
    )
    assert allowed.should_skip is False
    cfg = HooksConfig.from_mapping({"path_allowlist": ["/tmp"], "command_deny": []})
    assert cfg.path_allowlist == ("/tmp",)
    path_hook = PathAllowlistHook(allowlist=("/tmp",))
    skip = path_hook.before_tool_execution(
        ToolExecContext(
            snapshot=snap,
            tool_name="file_read",
            arguments={"path": "/etc/passwd"},
            working_dir=Path("."),
        )
    )
    assert skip.should_skip is True


@register_handler("structured_cards")
def handle_cards(case: EvalCase) -> None:
    del case
    tool = EmitCardTool()
    summary = tool.execute(
        {"kind": "summary", "title": "T", "bullets": ["a", "b"], "status": "ok"},
        Path("."),
    )
    assert is_structured_card_output(summary)
    assert "SUMMARY_CARD" in summary
    diff = tool.execute(
        {"kind": "code_diff", "path": "x.py", "diff": "+a\n"},
        Path("."),
    )
    assert "CODE_DIFF_CARD" in diff
    ref = tool.execute(
        {
            "kind": "reference",
            "references": [{"title": "Doc", "url": "https://example.com"}],
        },
        Path("."),
    )
    assert "REFERENCE_CARD" in ref
