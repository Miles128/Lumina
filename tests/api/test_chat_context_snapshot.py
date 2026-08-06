"""ChatResponse includes context_snapshot for harness UI."""

from __future__ import annotations

from secretary.agent.chat_service import ChatResult
from secretary.agent.llm_client import LlmUsage
from secretary.api.deps import to_chat_response


def test_to_chat_response_includes_context_snapshot() -> None:
    result = ChatResult(
        reply="ok",
        profile_excerpt="",
        used_llm=True,
        memory_hits=0,
        context_snapshot={
            "trace_id": "t1",
            "thread_id": "th1",
            "captured_at": "2026-08-04T00:00:00+00:00",
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cache_hit_tokens": None,
                "cache_miss_tokens": None,
                "estimated_prompt_tokens": 3,
            },
            "compaction": {"before_tokens": None, "after_tokens": None},
            "messages": [
                {"index": 0, "role": "user", "content": "hello", "approx_tokens": 1},
            ],
            "message_count": 1,
            "approx_total_tokens": 3,
        },
    )
    usage = LlmUsage(prompt_tokens=11, completion_tokens=2, total_tokens=13)
    response = to_chat_response(result, usage)
    assert response.context_snapshot is not None
    assert response.context_snapshot.messages[0].content == "hello"
    assert response.context_snapshot.usage.prompt_tokens == 11
    assert response.context_snapshot.usage.total_tokens == 13
    assert response.usage_total_tokens == 13
