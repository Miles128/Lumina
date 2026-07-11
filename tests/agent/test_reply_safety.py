"""Tests for reply safety filter."""

from secretary.agent.reply_safety import (
    contains_profanity,
    is_third_person_meta_reply,
    sanitize_user_facing_reply,
    strip_reasoning_chain,
)
from secretary.agent.reply_safety_rules import (
    load_forbidden_term_replacements,
    load_meta_reply_patterns,
    load_profanity_patterns,
    load_unprofessional_patterns,
    rules_dir,
)


def test_reply_safety_rules_md_files_exist_and_load() -> None:
    assert (rules_dir() / "profanity.md").is_file()
    assert (rules_dir() / "unprofessional.md").is_file()
    assert (rules_dir() / "meta-reply.md").is_file()
    assert (rules_dir() / "forbidden-terms.md").is_file()
    assert any(p.search("我靠") for p in load_profanity_patterns())
    assert load_unprofessional_patterns()
    assert load_meta_reply_patterns()
    assert ("用户", "你") in load_forbidden_term_replacements()


def test_profanity_allows_normal_compounds() -> None:
    for text in ("可以挂靠到技能目录", "这个方案很可靠", "傻子也会犯错", "别装傻", "靠谱一点"):
        assert not contains_profanity(text), text


def test_profanity_detects_swear_forms() -> None:
    for text in ("我靠", "靠你", "靠！", "傻逼", "他妈的，这个回答垃圾", "装逼"):
        assert contains_profanity(text), text


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


def test_sanitize_does_not_mask_profanity_with_stars() -> None:
    raw = "他妈的，这个回答垃圾"
    fixed = sanitize_user_facing_reply(raw, "请你帮我")
    assert "***" not in fixed
    assert contains_profanity(fixed)


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


def test_sanitize_leaves_slang_for_llm_rewrite() -> None:
    fixed = sanitize_user_facing_reply("这个方案有点装逼", "你怎么看")
    assert "装逼" in fixed
    assert "***" not in fixed


def test_sanitize_no_longer_calls_gentle_tone_noop() -> None:
    """Regression: empty gentle-tone helper was removed; sanitize must still return text."""
    assert sanitize_user_facing_reply("你好", "嗨") == "你好"


def test_sanitize_strips_reasoning_before_display() -> None:
    open_tag = "<" + "think" + ">"
    close_tag = "</" + "think" + ">"
    raw = f"{open_tag}内部推理{close_tag}\n你好，我在。"
    fixed = sanitize_user_facing_reply(raw, "你好")
    assert "内部推理" not in fixed
    assert "你好，我在。" in fixed
