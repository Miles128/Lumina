"""Tests for reply safety filter."""

from secretary.agent.reply_safety import (
    is_third_person_meta_reply,
    sanitize_user_facing_reply,
    strip_reasoning_chain,
)


def test_detects_classifier_reason_leak() -> None:
    text = "用户未明确需求，情绪化反问，需等待用户提出具体问题"
    assert is_third_person_meta_reply(text)


def test_allows_normal_reply() -> None:
    assert not is_third_person_meta_reply("好的，我这就把提示词贴给你看。")


def test_sanitize_replaces_meta_reply() -> None:
    bad = "用户情绪激动，未明确具体需求"
    fixed = sanitize_user_facing_reply(bad, "你又行了？")
    assert "用户" not in fixed
    assert "你又行了" in fixed


def test_sanitize_filters_profanity_and_keeps_gentle_tone() -> None:
    fixed = sanitize_user_facing_reply("他妈的，这个回答垃圾", "请你帮我")
    assert "***" in fixed
    assert not fixed.startswith("你这个反馈很关键，我先直接处理问题。")


def test_sanitize_replaces_forbidden_label_everywhere() -> None:
    fixed = sanitize_user_facing_reply("用户指令模糊，需要澄清用户需求", "继续")
    assert "用户" not in fixed
    assert "你说的「继续」我听见了。" in fixed


def test_sanitize_rewrites_unprofessional_self_blame() -> None:
    fixed = sanitize_user_facing_reply("没有技术原因，就是我瞎了。", "为什么会漏")
    assert "瞎了" not in fixed
    assert "我这次判断失误" in fixed


def test_strip_reasoning_chain_removes_think_blocks() -> None:
    open_tag = "<" + "think" + ">"
    close_tag = "</" + "think" + ">"
    raw = f"{open_tag}先分析一下{close_tag}\n\n最终答案是：42"
    assert strip_reasoning_chain(raw) == "最终答案是：42"


def test_sanitize_strips_reasoning_before_display() -> None:
    open_tag = "<" + "think" + ">"
    close_tag = "</" + "think" + ">"
    raw = f"{open_tag}内部推理{close_tag}\n你好，我在。"
    fixed = sanitize_user_facing_reply(raw, "你好")
    assert "内部推理" not in fixed
    assert "你好，我在。" in fixed
