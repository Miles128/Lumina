"""Tests for native tool-call message pairing in AgentLoop."""

from secretary.agent.loop import ToolCall, assistant_message_for_tool_call, ensure_tool_call_id


def test_assistant_message_for_tool_call_keeps_single_tool_only() -> None:
    assistant_message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_a",
                "type": "function",
                "function": {"name": "list_dir", "arguments": "{\"path\": \".\"}"},
            },
            {
                "id": "call_b",
                "type": "function",
                "function": {"name": "file_read", "arguments": "{\"path\": \"a.txt\"}"},
            },
        ],
    }
    tool_call = ToolCall(name="list_dir", arguments={"path": "."}, id="call_a")
    paired = assistant_message_for_tool_call(assistant_message, tool_call)
    assert len(paired["tool_calls"]) == 1
    assert paired["tool_calls"][0]["id"] == "call_a"
    assert paired["tool_calls"][0]["function"]["name"] == "list_dir"


def test_ensure_tool_call_id_generates_fallback() -> None:
    tool_call = ToolCall(name="list_dir", arguments={"path": "."})
    paired = ensure_tool_call_id(tool_call, suffix="0")
    assert paired.id == "call_list_dir_0"
