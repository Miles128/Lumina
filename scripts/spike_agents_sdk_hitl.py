"""Spike: OpenAI Agents SDK (0.19.x) × DeepSeek HITL 链路验证.

验证 4 点:
  1. DeepSeek 经 Chat Completions 兼容模式 + tool calling 跑通
  2. needs_approval 暂停 -> interruptions -> approve -> resume
  3. RunState.to_string/from_string 跨"重启"恢复
  4. Agent.as_tool 嵌套: 内层工具的审批浮到外层 run
  5. thinking 参数是否可透传 (extra_body)

从 ~/.lumina/agent.json 读取配置, 不打印密钥。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from openai import OpenAI

KEY = ""
MODEL = "deepseek-v4-flash"
BASE = "https://api.deepseek.com"


def _load_config() -> None:
    global KEY, MODEL, BASE
    cfg_path = Path(os.path.expanduser("~/.lumina/agent.json"))
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    KEY = str(cfg.get("api_key") or "").strip()
    if cfg.get("base_url"):
        BASE = str(cfg["base_url"]).rstrip("/")
    if cfg.get("model"):
        MODEL = str(cfg["model"])
    assert KEY, "agent.json 缺少 api_key"


def _client():
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=KEY, base_url=BASE)


def check_thinking_direct() -> bool:
    """直接打 OpenAI SDK: DeepSeek 是否接受 extra_body thinking."""
    import asyncio

    async def go() -> str:
        resp = await _client().chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "1+1=?"}],
            max_tokens=32,
            extra_body={"thinking": {"type": "enabled"}},
        )
        return resp.choices[0].message.content or ""

    try:
        reply = asyncio.run(go())
        print(f"[5] extra_body thinking OK, reply={reply!r}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[5] extra_body thinking FAILED: {type(exc).__name__}: {str(exc)[:200]}")
        return False


def main() -> None:
    _load_config()
    from agents import Agent, RunState, Runner, set_default_openai_api, set_default_openai_client
    from agents.decorators import function_tool

    set_default_openai_client(_client(), use_for_tracing=False)
    set_default_openai_api("chat_completions")
    print(f"provider=deepseek base={BASE} model={MODEL}")

    # ---- 1+2: 顶层工具审批暂停/恢复 ----
    @function_tool(needs_approval=True)
    def delete_file(path: str) -> str:
        return f"deleted {path}"

    @function_tool
    def get_cwd() -> str:
        return "spike-cwd"

    top = Agent(
        name="spike-top",
        instructions="你是测试助手。回答用户问题时按需调用工具。",
        tools=[delete_file, get_cwd],
        model=MODEL,
    )

    result = Runner.run_sync(
        top,
        "当前目录是什么？另外把 /tmp/spike-xxx.txt 删除",
        max_turns=6,
    )
    print(f"\n[1+2] run 完成: interruptions={len(result.interruptions)}")
    for item in result.interruptions:
        print(f"      pending: tool={item.name!r} args={item.arguments} agent={item.agent.name!r}")
    assert result.interruptions, "预期出现审批暂停, 实际没有!"
    assert any(i.name == "delete_file" for i in result.interruptions)
    print("[1+2] 暂停正确: delete_file 浮出为 interruption")

    # 批准后恢复
    state = result.to_state()
    for item in result.interruptions:
        state.approve(item, always_approve=True)
    resumed = Runner.run_sync(top, state, max_turns=6)
    print(f"[1+2] resume 完成: final_output={resumed.final_output!r}")
    assert "spike-cwd" in str(resumed.final_output), "resume 后上下文丢失?"
    print("[1+2] approve+resume OK")

    # ---- 3: RunState 序列化跨重启 ----
    paused = Runner.run_sync(top, "把 /tmp/spike-b.txt 删除", max_turns=6)
    assert paused.interruptions, "预期第二个暂停"

    async def _roundtrip() -> str:
        state = paused.to_state()
        serialized = state.to_string()
        restored = await RunState.from_string(top, serialized)
        for item in restored.get_interruptions():
            restored.approve(item)
        finished = await Runner.run(top, restored, max_turns=6)
        return str(finished.final_output)

    import asyncio

    out = asyncio.run(_roundtrip())
    print(f"[3] RunState 序列化往返 + 恢复 OK, final_output={out!r}")
    assert "/tmp/spike-b.txt" in out

    # ---- 4: 嵌套 Agent.as_tool 审批浮到外层 ----
    @function_tool(needs_approval=True)
    def drop_table(table: str) -> str:
        return f"dropped {table}"

    inner = Agent(
        name="spike-inner",
        instructions="你是数据库助手, 用工具完成任务。",
        tools=[drop_table],
        model=MODEL,
    )
    outer = Agent(
        name="spike-outer",
        instructions="你是主管, 可委派给子助手。",
        tools=[inner.as_tool(
            tool_name="delegate_db",
            tool_description="委派给数据库子助手执行表操作",
        )],
        model=MODEL,
    )
    nested = Runner.run_sync(outer, "让子助手把 orders 表删掉", max_turns=6)
    print(f"[4] 嵌套 run: interruptions={len(nested.interruptions)}")
    for item in nested.interruptions:
        print(f"      pending: tool={item.name!r} args={item.arguments}")
    assert nested.interruptions, "预期嵌套审批浮到外层, 实际没有!"
    assert any(i.name == "drop_table" for i in nested.interruptions)
    print("[4] 嵌套审批浮出外层 OK")

    print("\n=== SPIKE 全部通过 ===")


if __name__ == "__main__":
    main()
    check_thinking_direct()
