"""parse_tool_call_response must recover <function_calls> XML tool calls.

Some models (notably DeepSeek) emit tool calls as XML in the content body
instead of the structured ``tool_calls`` field. Lumina's native path returns
no ``tool_calls`` in that case, so the text parser must recover them.
"""

from __future__ import annotations

from secretary.agent.loop_prompting import parse_tool_call_response


def test_parse_function_calls_xml_single_invoke() -> None:
    raw = (
        "我来读一下 README。\n"
        "<function_calls>\n"
        "<invoke name=\"file_read\">\n"
        "<parameter name=\"path\">/Users/sihai/Documents/My Projects/StockResearch/README.md</parameter>\n"
        "</invoke>\n"
        "</function_calls>"
    )
    thought, call = parse_tool_call_response(raw)
    assert call is not None
    assert call.name == "file_read"
    assert call.arguments.get("path") == "/Users/sihai/Documents/My Projects/StockResearch/README.md"
    assert "我来读一下" in thought
    assert "<function_calls>" not in thought


def test_parse_function_calls_xml_file_path_alias() -> None:
    raw = (
        "<function_calls>\n"
        "<invoke name=\"file_read\">\n"
        "<parameter name=\"file_path\">/tmp/x.py</parameter>\n"
        "</invoke>\n"
        "</function_calls>"
    )
    _, call = parse_tool_call_response(raw)
    assert call is not None
    assert call.name == "file_read"
    assert call.arguments.get("file_path") == "/tmp/x.py"


def test_parse_function_calls_xml_returns_first_of_multiple() -> None:
    raw = (
        "<function_calls>\n"
        "<invoke name=\"file_read\"><parameter name=\"path\">/a.py</parameter></invoke>\n"
        "<invoke name=\"file_read\"><parameter name=\"path\">/b.py</parameter></invoke>\n"
        "</function_calls>"
    )
    _, call = parse_tool_call_response(raw)
    assert call is not None
    assert call.arguments.get("path") == "/a.py"


def test_parse_function_calls_xml_absent_falls_through() -> None:
    # No fence, no XML, no shell — returns no tool call.
    thought, call = parse_tool_call_response("这是一个普通回答，没有工具。")
    assert call is None
    assert thought == "这是一个普通回答，没有工具。"


def test_fence_tool_call_still_preferred_over_xml() -> None:
    raw = (
        "```tool-call\n"
        '{"name": "list_dir", "arguments": {"path": "."}}\n'
        "```\n"
        "<function_calls><invoke name=\"file_read\"><parameter name=\"path\">/x</parameter></invoke></function_calls>"
    )
    _, call = parse_tool_call_response(raw)
    assert call is not None
    assert call.name == "list_dir"
