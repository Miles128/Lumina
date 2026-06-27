"""Tests for filesystem grounding heuristics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from secretary.agent.grounding import (
    ReadEvidence,
    collect_read_evidence,
    has_read_grounding,
    is_filesystem_question,
    mentions_local_files,
    should_retry_for_grounding,
    should_retry_for_verification,
    verify_reply_against_evidence,
)


@dataclass
class _FakeToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class _FakeStep:
    tool_call: _FakeToolCall | None
    tool_output: str | None


def test_is_filesystem_question_detects_file_queries() -> None:
    assert is_filesystem_question("帮我看看 README.md 写了什么")
    assert is_filesystem_question("Lumina 项目里有哪些 Python 文件")
    assert is_filesystem_question("open-design 作者是谁")
    assert not is_filesystem_question("今天天气怎么样")
    assert not is_filesystem_question("GitHub 最近一周最火的项目都有哪些？")
    assert is_filesystem_question("我手上都有哪些项目，在 my project 文件夹里")


def test_enforce_does_not_block_web_questions() -> None:
    from secretary.agent.grounding import UNGROUNDED_LISTING_FALLBACK, enforce_grounded_reply

    reply = "根据检索，本周 GitHub 上较热的 repo 包括 …"
    kept, verified, _ = enforce_grounded_reply(
        reply,
        "GitHub 最近一周最火的项目都有哪些？",
        [],
        grounding_verified=False,
        grounding_note="",
    )
    assert kept == reply
    assert verified is True
    assert UNGROUNDED_LISTING_FALLBACK not in kept

    kept2, verified2, _ = enforce_grounded_reply(
        reply,
        "GitHub 最近一周最火的项目都有哪些？",
        ["web_search"],
        grounding_verified=True,
        grounding_note="",
    )
    assert kept2 == reply
    assert verified2 is True


def test_mentions_local_files_detects_paths() -> None:
    assert mentions_local_files("在 src/secretary/agent/loop.py 里")
    assert mentions_local_files("config.json 里配置了 API key")
    assert mentions_local_files("好，那我再查一下 ~/Documents/My Projects/ 目录下的内容。")
    assert not mentions_local_files("你可以先列一下需求")


def test_resolve_turn_user_message_skips_grounding_retry() -> None:
    from secretary.agent.grounding import GROUNDING_RETRY_USER, resolve_turn_user_message

    messages = [
        {"role": "system", "content": "你是灵犀"},
        {"role": "user", "content": "GitHub 最近一周最火的项目都有哪些？"},
        {"role": "assistant", "content": "稍等"},
        {"role": "user", "content": GROUNDING_RETRY_USER},
    ]
    assert resolve_turn_user_message(messages) == "GitHub 最近一周最火的项目都有哪些？"


def test_should_not_retry_grounding_after_web_search() -> None:
    from secretary.agent.grounding import should_retry_for_grounding

    reply = "1. harry0703/MoneyPrinterTurbo\n2. microsoft/markitdown\n3. Lum1104/Understand-Anything"
    assert not should_retry_for_grounding(
        "GitHub 最近一周最火的项目都有哪些？",
        reply,
        ["web_search", "web_fetch"],
    )


def test_enforce_after_web_search_with_grounding_retry_in_history() -> None:
    from secretary.agent.grounding import enforce_grounded_reply

    reply = "本周 GitHub Trending：MoneyPrinterTurbo、markitdown、Understand-Anything …"
    kept, verified, note = enforce_grounded_reply(
        reply,
        "你会上网查这个信息吗？GitHub 最近一周最火的项目都有哪些？",
        ["web_search", "web_fetch"],
        grounding_verified=False,
        grounding_note="",
    )
    assert verified
    assert "无法确认" not in kept
    assert "web_search" in note or "联网" in note


def test_deferral_reply_triggers_retry() -> None:
    from secretary.agent.grounding import reply_defers_filesystem_work

    promise = "好，那我再查一下 ~/Documents/My Projects/ 目录。稍等，查完告诉你。"
    assert reply_defers_filesystem_work(promise)
    assert should_retry_for_grounding(
        "查一下 ~/Documents/My Projects/ 里有哪些项目",
        promise,
        [],
    )


def test_infer_list_dir_target_handles_spaces() -> None:
    from secretary.agent.grounding import infer_list_dir_target

    target = infer_list_dir_target(
        "查一下 ~/Documents/My Projects/ 目录下的内容",
        "我再查 ~/Documents/My Projects/",
    )
    assert target is not None
    assert "My Projects" in target
    assert "有哪些" not in target


def test_infer_list_dir_target_strips_chinese_suffix(tmp_path: Path) -> None:
    from secretary.agent.grounding import infer_list_dir_target

    projects = tmp_path / "My Projects"
    projects.mkdir()
    target = infer_list_dir_target(
        f"查一下 {projects} 里有哪些项目",
        "好，我查 /Users/sihai/Documents/My Projects/ 目录下的内容。稍等，查完告诉你。",
    )
    assert target is not None
    assert str(projects.resolve()) == target or "My Projects" in target
    assert "稍等" not in target
    assert "有哪些" not in target


def test_has_read_grounding() -> None:
    assert has_read_grounding(["file_read"])
    assert has_read_grounding(["mcp_filesystem_read_file"])
    assert not has_read_grounding(["shell", "web_search"])


def test_should_retry_when_ungrounded() -> None:
    assert should_retry_for_grounding(
        "读一下 package.json",
        "package.json 里有 react 依赖",
        [],
    )
    assert not should_retry_for_grounding(
        "读一下 package.json",
        "内容是…",
        ["file_read"],
    )
    assert not should_retry_for_grounding(
        "你好",
        "你好呀",
        [],
    )


def test_collect_read_evidence_from_file_read() -> None:
    steps = [
        _FakeStep(
            tool_call=_FakeToolCall(name="file_read", arguments={"path": "README.md"}),
            tool_output="📄 /tmp/README.md (10 lines, 1.2KB)\n1: hello",
        )
    ]
    evidence = collect_read_evidence(steps)
    assert evidence.read_files
    assert any("readme.md" in item for item in evidence.read_files)


def test_requires_forced_read_tool() -> None:
    from secretary.agent.grounding import requires_forced_read_tool

    assert requires_forced_read_tool("列出 ~/Documents/简历/", [])
    assert not requires_forced_read_tool("列出 ~/Documents/简历/", ["list_dir"])


def test_strip_forbidden_listing_patterns() -> None:
    from secretary.agent.grounding import strip_forbidden_listing_patterns

    raw = "~/Documents/简历/\n├── a.md\n├── b.md\n真实说明"
    cleaned = strip_forbidden_listing_patterns(raw)
    assert "├──" not in cleaned
    assert "真实说明" in cleaned


def test_verify_reply_flags_ungrounded_paths() -> None:
    evidence = ReadEvidence(
        read_files={"/tmp/readme.md"},
        listed_names={"README.md"},
    )
    ok = verify_reply_against_evidence(
        "src/secretary/agent/missing.py 里实现了验证",
        evidence,
        "项目里有哪些文件",
    )
    assert not ok.ok
    assert should_retry_for_verification(ok)


def test_reply_simulates_file_listing_detects_fake_ls() -> None:
    from secretary.agent.grounding import enforce_grounded_reply, reply_simulates_file_listing

    fake = "$ ls -la ~/Documents/简历/\ntotal 48\n-rw-r--r-- 简历_产品经理方向.md"
    assert reply_simulates_file_listing(fake)
    tree = "~/Documents/简历/\n├── a.md\n├── b.md\n├── c.md"
    assert reply_simulates_file_listing(tree)

    replaced, verified, note = enforce_grounded_reply(
        tree,
        "列出简历文件夹",
        [],
        grounding_verified=True,
        grounding_note="",
    )
    assert not verified
    assert "无法确认" in replaced
    assert note


def test_is_personal_memory_question_and_enforce_memory() -> None:
    from secretary.agent.grounding import (
        UNGROUNDED_MEMORY_FALLBACK,
        enforce_grounded_reply,
        is_memory_write_request,
        is_personal_memory_question,
    )

    assert is_personal_memory_question("再找")
    assert is_personal_memory_question("总结一下我最近在读什么")
    assert is_personal_memory_question("根据我的记忆总结一下")
    assert is_memory_write_request("写入记忆：我喜欢 Python")
    assert is_memory_write_request("记住我喜欢深色模式")
    assert not is_personal_memory_question("写入记忆：我喜欢 Python")
    assert not is_personal_memory_question("你记住了吗")
    reply = (
        "翻了对话历史，你提到的书就这两本：\n"
        "1. **《启示录》**\n"
        "2. **《俞军产品方法论》**"
    )
    blocked, verified, _note = enforce_grounded_reply(
        reply,
        "再找",
        [],
        grounding_verified=True,
        grounding_note="",
    )
    assert not verified
    assert blocked == UNGROUNDED_MEMORY_FALLBACK

    kept, verified, _ = enforce_grounded_reply(
        reply,
        "再找",
        ["search_memory"],
        grounding_verified=True,
        grounding_note="",
    )
    assert verified
    assert kept == reply


def test_mcp_list_directory_populates_evidence() -> None:
    from secretary.agent.grounding import collect_read_evidence, enforce_grounded_reply

    output = (
        "[FILE] .DS_Store\n"
        "[DIR] Lumina\n"
        "[DIR] open-design\n"
    )
    steps = [
        _FakeStep(
            tool_call=_FakeToolCall(
                name="mcp_filesystem_list_directory",
                arguments={"path": "/Users/me/Documents/My Projects"},
            ),
            tool_output=output,
        )
    ]
    evidence = collect_read_evidence(steps)
    assert "Lumina" in evidence.listed_names
    assert "open-design" in evidence.listed_names

    reply = "你的 My Projects 里有：Lumina、open-design 等。"
    kept, verified, _ = enforce_grounded_reply(
        reply,
        "我手上都有哪些项目，在 my project 文件夹",
        ["mcp_filesystem_list_directory"],
        grounding_verified=False,
        grounding_note="",
    )
    assert verified
    assert kept == reply


def test_enforce_grounded_reply_allows_search_files_listing_when_verified() -> None:
    from secretary.agent.grounding import enforce_grounded_reply, reply_simulates_file_listing

    reply = (
        "~/Documents/简历/ 下找到这些文件：\n"
        "买宇翔_金融产品经理.md\n"
        "买宇翔_金融 AI 产品.md\n"
        "买宇翔_蚂蚁金服_大模型风险管理.md\n"
        "买宇翔_基金运营总监.md\n"
        "买宇翔_AI产品经理.md\n"
        "买宇翔_AI产品经理.html"
    )
    assert reply_simulates_file_listing(reply)

    kept, verified, _note = enforce_grounded_reply(
        reply,
        "列出 ~/Documents/简历/ 里所有文件",
        ["search_files"],
        grounding_verified=True,
        grounding_note="",
    )
    assert verified
    assert kept == reply
    assert "无法确认" not in kept
