"""Tests for the command execution receipt system.

Covers: fake shell session detection, prose claim detection, receipt extraction,
command evidence collection, verify/enforce integration, and tag stripping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from secretary.agent.grounding import (
    UNGROUNDED_COMMAND_FALLBACK,
    CommandEvidence,
    ReadEvidence,
    collect_command_evidence,
    enforce_grounded_reply,
    extract_receipt_refs,
    reply_claims_command_execution,
    reply_claims_or_simulates_command_execution,
    reply_simulates_command_execution,
    strip_receipt_tags,
    verify_command_receipts,
    verify_reply_against_evidence,
)


@dataclass
class _FakeToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = ""


@dataclass
class _FakeStep:
    tool_call: _FakeToolCall | None
    tool_output: str | None = None


# --- Detection: fake shell session ---


def test_simulates_command_execution_detects_fake_pytest_banner() -> None:
    assert reply_simulates_command_execution(
        "我跑了测试，结果：\n===== 3 failed, 5 passed in 0.4s ====="
    )


def test_simulates_command_execution_detects_fake_exit_code() -> None:
    assert reply_simulates_command_execution("命令执行完，exit code: 0")


def test_simulates_command_execution_detects_fake_shell_prompt() -> None:
    assert reply_simulates_command_execution("$ pytest -v\n collecting ...")


def test_simulates_command_execution_detects_build_success() -> None:
    assert reply_simulates_command_execution("Build successful")


def test_simulates_command_execution_detects_no_output() -> None:
    assert reply_simulates_command_execution("运行完成\n(no output)")


def test_simulates_command_execution_ignores_normal_reply() -> None:
    assert not reply_simulates_command_execution("这是一个普通的回答，没有命令输出")
    assert not reply_simulates_command_execution("")


def test_simulates_command_execution_does_not_flag_dollar_ls() -> None:
    # `$ ls` is handled by file listing detection, not command execution.
    assert not reply_simulates_command_execution("$ ls ~/Documents")


# --- Detection: prose claims ---


def test_claims_command_execution_detects_pytest_claim() -> None:
    assert reply_claims_command_execution("我跑了 pytest，3 个失败")


def test_claims_command_execution_detects_test_passed_marker() -> None:
    assert reply_claims_command_execution("测试通过，没问题")


def test_claims_command_execution_detects_already_npm() -> None:
    assert reply_claims_command_execution("已经 npm install 完了")


def test_claims_command_execution_detects_i_ran_git() -> None:
    assert reply_claims_command_execution("I ran git log to check recent commits")


def test_claims_command_execution_ignores_suggestion() -> None:
    assert not reply_claims_command_execution("你可以跑 pytest 看看")
    assert not reply_claims_command_execution("建议执行 npm install")


def test_claims_command_execution_ignores_history_reference() -> None:
    assert not reply_claims_command_execution("上次跑 pytest 的时候也失败了")


def test_claims_command_execution_ignores_generic_list_dir_claim() -> None:
    # "我跑了 list_dir" without a shell command name should not trigger
    # (list_dir is a read tool, not a shell command).
    assert not reply_claims_command_execution("我跑了 list_dir 看了一下目录")


def test_claims_or_simulates_combines_both() -> None:
    assert reply_claims_or_simulates_command_execution("$ npm run build")
    assert reply_claims_or_simulates_command_execution("我跑了 pytest")
    assert not reply_claims_or_simulates_command_execution("普通回答")


# --- Receipt tag extraction & stripping ---


def test_extract_receipt_refs() -> None:
    refs = extract_receipt_refs(
        "我跑了 pytest [receipt:call_shell_3]，结果如下 [receipt:call_shell_5]"
    )
    assert refs == {"call_shell_3", "call_shell_5"}


def test_extract_receipt_refs_empty_when_no_tags() -> None:
    assert extract_receipt_refs("没有任何 receipt 标记") == set()


def test_strip_receipt_tags_removes_all_tags() -> None:
    cleaned = strip_receipt_tags(
        "我跑了 pytest [receipt:call_shell_3]，通过了 [receipt:call_shell_5]"
    )
    assert "[receipt:" not in cleaned
    assert "我跑了 pytest，通过了" in cleaned


def test_strip_receipt_tags_preserves_other_text() -> None:
    cleaned = strip_receipt_tags("普通回答，没有标签")
    assert cleaned == "普通回答，没有标签"


# --- Command evidence collection ---


def test_collect_command_evidence_collects_shell_receipts() -> None:
    steps = [
        _FakeStep(
            tool_call=_FakeToolCall(
                name="shell",
                arguments={"command": "pytest -v"},
                id="call_shell_3",
            ),
            tool_output="3 failed, 5 passed",
        ),
        _FakeStep(
            tool_call=_FakeToolCall(
                name="list_dir",
                arguments={"path": "."},
                id="call_list_dir_1",
            ),
            tool_output="📄 a.py",
        ),
        _FakeStep(
            tool_call=_FakeToolCall(
                name="shell",
                arguments={"command": "npm run build"},
                id="call_shell_5",
            ),
            tool_output="Build successful",
        ),
    ]
    evidence = collect_command_evidence(steps)
    assert evidence.shell_receipts == {
        "call_shell_3": "pytest -v",
        "call_shell_5": "npm run build",
    }
    assert evidence.receipt_ids == {"call_shell_3", "call_shell_5"}


def test_collect_command_evidence_empty_when_no_shell() -> None:
    steps = [
        _FakeStep(
            tool_call=_FakeToolCall(
                name="list_dir", arguments={"path": "."}, id="call_list_dir_1"
            ),
            tool_output="📄 a.py",
        )
    ]
    evidence = collect_command_evidence(steps)
    assert evidence.shell_receipts == {}


def test_collect_command_evidence_skips_shell_without_id() -> None:
    steps = [
        _FakeStep(
            tool_call=_FakeToolCall(
                name="shell", arguments={"command": "pytest"}, id=""
            ),
            tool_output="ok",
        )
    ]
    evidence = collect_command_evidence(steps)
    assert evidence.shell_receipts == {}


# --- Verification ---


def test_verify_command_receipts_passes_when_no_claim() -> None:
    evidence = CommandEvidence()
    result = verify_command_receipts("普通回答，不涉及命令执行", evidence)
    assert result.ok is True


def test_verify_command_receipts_fails_when_claim_without_receipt() -> None:
    evidence = CommandEvidence()
    result = verify_command_receipts("我跑了 pytest，3 个失败", evidence)
    assert result.ok is False
    assert "未引用任何 receipt" in result.note


def test_verify_command_receipts_fails_when_receipt_id_unknown() -> None:
    evidence = CommandEvidence(shell_receipts={"call_shell_3": "pytest"})
    result = verify_command_receipts(
        "我跑了 pytest [receipt:call_shell_99]", evidence
    )
    assert result.ok is False
    assert "不存在" in result.note


def test_verify_command_receipts_passes_when_receipt_valid() -> None:
    evidence = CommandEvidence(shell_receipts={"call_shell_3": "pytest"})
    result = verify_command_receipts(
        "我跑了 pytest [receipt:call_shell_3]，3 个失败", evidence
    )
    assert result.ok is True


def test_verify_command_receipts_passes_when_simulated_output_has_valid_receipt() -> None:
    evidence = CommandEvidence(shell_receipts={"call_shell_3": "pytest"})
    result = verify_command_receipts(
        "结果如下 [receipt:call_shell_3]：\n===== 3 failed =====", evidence
    )
    assert result.ok is True


# --- verify_reply_against_evidence integration ---


def test_verify_reply_against_evidence_catches_command_claim_for_non_fs_question() -> None:
    # Non-filesystem question (no file markers) — previously slipped through.
    evidence = ReadEvidence()
    cmd_evidence = CommandEvidence()  # no shell receipts
    result = verify_reply_against_evidence(
        "我跑了 pytest，测试通过",
        evidence,
        "跑一下测试看看",
        command_evidence=cmd_evidence,
    )
    assert result.ok is False
    assert "receipt" in result.note


def test_verify_reply_against_evidence_skips_command_check_without_evidence() -> None:
    # Backward compat: no command_evidence passed → no command check.
    evidence = ReadEvidence()
    result = verify_reply_against_evidence(
        "我跑了 pytest",
        evidence,
        "跑一下测试看看",
    )
    assert result.ok is True  # not a filesystem question, no command check


# --- enforce_grounded_reply integration ---


def test_enforce_returns_command_fallback_when_claim_without_receipt() -> None:
    cmd_evidence = CommandEvidence()  # no shell receipts
    reply, verified, note = enforce_grounded_reply(
        "我跑了 pytest，3 个失败，测试通过",
        "跑一下测试看看",
        [],
        grounding_verified=False,
        grounding_note="",
        command_evidence=cmd_evidence,
    )
    assert reply == UNGROUNDED_COMMAND_FALLBACK
    assert verified is False
    assert "receipt" in note


def test_enforce_returns_command_fallback_when_receipt_unknown() -> None:
    cmd_evidence = CommandEvidence(shell_receipts={"call_shell_3": "pytest"})
    reply, verified, note = enforce_grounded_reply(
        "我跑了 pytest [receipt:call_shell_99]",
        "跑一下测试看看",
        [],
        grounding_verified=False,
        grounding_note="",
        command_evidence=cmd_evidence,
    )
    assert reply == UNGROUNDED_COMMAND_FALLBACK
    assert verified is False


def test_enforce_strips_receipt_tags_when_receipts_valid() -> None:
    cmd_evidence = CommandEvidence(shell_receipts={"call_shell_3": "pytest"})
    reply, verified, _ = enforce_grounded_reply(
        "我跑了 pytest [receipt:call_shell_3]，3 个失败",
        "测试跑得怎么样",
        [],
        grounding_verified=True,
        grounding_note="",
        command_evidence=cmd_evidence,
    )
    assert "[receipt:" not in reply
    assert "我跑了 pytest" in reply
    assert verified is True


def test_enforce_strips_receipt_tags_even_without_command_evidence() -> None:
    # Backward compat: no command_evidence, but tags still stripped.
    reply, _, _ = enforce_grounded_reply(
        "普通回答 [receipt:call_shell_3]",
        "普通问题",
        [],
        grounding_verified=True,
        grounding_note="",
    )
    assert "[receipt:" not in reply
    assert "普通回答" in reply


def test_enforce_does_not_block_suggestion() -> None:
    cmd_evidence = CommandEvidence()
    reply, verified, _ = enforce_grounded_reply(
        "你可以跑 pytest 看看",
        "怎么测试",
        [],
        grounding_verified=False,
        grounding_note="",
        command_evidence=cmd_evidence,
    )
    assert reply == "你可以跑 pytest 看看"
    assert verified is False  # passes through grounding_verified


def test_enforce_command_check_runs_before_filesystem_check() -> None:
    # A filesystem question with a command claim — command check should fire.
    cmd_evidence = CommandEvidence()
    reply, verified, note = enforce_grounded_reply(
        "我跑了 pytest，测试通过",
        "看看 src/ 目录",  # filesystem question
        [],
        grounding_verified=False,
        grounding_note="",
        command_evidence=cmd_evidence,
    )
    assert reply == UNGROUNDED_COMMAND_FALLBACK
    assert "receipt" in note
