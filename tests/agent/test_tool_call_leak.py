"""Leaked <function_calls> XML must never reach the user as a final answer."""

from __future__ import annotations

from secretary.agent.loop_prompting import reply_contains_tool_call_markup
from secretary.agent.reply_safety import sanitize_user_facing_reply, strip_tool_call_markup


def test_detect_function_calls_leak() -> None:
    raw = (
        "<function_calls>\n"
        '<invoke name="list_dir">\n'
        '<parameter name="path">.</parameter>\n'
        "</invoke>\n"
        "</function_calls>"
    )
    assert reply_contains_tool_call_markup(raw)
    assert not reply_contains_tool_call_markup("普通分析结论，没有工具调用。")


def test_strip_tool_call_markup_removes_xml() -> None:
    raw = (
        "我先列目录。\n"
        "<function_calls>\n"
        '<invoke name="list_dir">\n'
        '<parameter name="path">.</parameter>\n'
        "</invoke>\n"
        "</function_calls>"
    )
    cleaned = strip_tool_call_markup(raw)
    assert "<function_calls>" not in cleaned
    assert "list_dir" not in cleaned
    assert "我先列目录" in cleaned


def test_sanitize_strips_tool_call_leak() -> None:
    raw = (
        "<function_calls>\n"
        '<invoke name="list_dir">\n'
        '<parameter name="path">.</parameter>\n'
        "</invoke>\n"
        "</function_calls>"
    )
    out = sanitize_user_facing_reply(raw, "再分析一遍")
    assert "<function_calls>" not in out
    assert "<invoke" not in out


def test_detect_and_strip_dsml_tool_leak() -> None:
    raw = (
        "我先定位 MEMORY.md。\n"
        "<｜｜DSML｜｜tool_calls>\n"
        '<｜｜DSML｜｜invoke name="glob">\n'
        '<｜｜DSML｜｜parameter name="pattern" string="true">**/MEMORY.md</｜｜DSML｜｜parameter>\n'
        "</｜｜DSML｜｜invoke>\n"
        "</｜｜DSML｜｜tool_calls>"
    )
    assert reply_contains_tool_call_markup(raw)
    cleaned = strip_tool_call_markup(raw)
    assert "DSML" not in cleaned
    assert "glob" not in cleaned
    assert "tool_calls" not in cleaned
    assert "我先定位" in cleaned
    assert "MEMORY.md" in cleaned
