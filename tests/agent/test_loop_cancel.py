from pathlib import Path

from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import AgentLoop
from secretary.agent.tools.base import Tool


class RecordingTool(Tool):
    name = "record"
    description = "Record one execution"

    def __init__(self, on_execute) -> None:
        self.calls = 0
        self._on_execute = on_execute

    def execute(self, arguments: dict[str, object], working_dir: Path) -> str:
        self.calls += 1
        self._on_execute()
        return "recorded"


def test_agent_loop_stops_when_cancelled_between_iterations(monkeypatch) -> None:
    cancelled = False

    def cancel_check() -> bool:
        return cancelled

    def cancel_after_tool() -> None:
        nonlocal cancelled
        cancelled = True

    tool = RecordingTool(cancel_after_tool)

    def fake_chat_completion(*args, **kwargs) -> str:
        return """I'll use the tool.

```tool-call
{"name": "record", "arguments": {}}
```"""

    monkeypatch.setattr("secretary.agent.loop.chat_completion", fake_chat_completion)
    loop = AgentLoop(
        LlmConfig(
            api_key="test-key",
            base_url="https://example.com/v1",
            model="test-model",
            source="test",
        ),
        tools=[tool],
        cancel_check=cancel_check,
    )
    loop._native_tools_enabled = False

    result = loop.run([{"role": "user", "content": "run the tool twice"}])

    assert result.reply == "已取消。"
    assert result.cancelled is True
    assert result.used_tools == ["record"]
    assert tool.calls == 1
