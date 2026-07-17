"""Tests for web/realtime query routing."""

from __future__ import annotations

from secretary.agent.web_routing import (
    WebIntentRouter,
    _parse_web_intent,
    build_search_query,
    is_web_search_query,
    resolve_web_search,
    resolve_web_search_with_llm_fallback,
)
from secretary.config import Settings


def test_weather_is_web_search() -> None:
    assert is_web_search_query("今天天气怎么样")


def test_weather_with_location_enriches_query() -> None:
    query = build_search_query("今天天气怎么样", location_city="杭州")
    assert query == "杭州 今天天气 气温"


def test_weather_without_location_uses_raw_message() -> None:
    query = build_search_query("今天天气怎么样")
    assert query == "今天天气怎么样"


def test_weather_explicit_city_in_message() -> None:
    query = build_search_query("杭州天气怎么样", location_city="上海")
    assert query == "杭州 今天天气 气温"


def test_weather_followup_city() -> None:
    history = [
        {"role": "user", "content": "今天天气怎么样"},
        {"role": "assistant", "content": "请稍等"},
    ]
    assert build_search_query("杭州", history) == "杭州 今天天气 气温"


def test_web_search_query_markers() -> None:
    assert is_web_search_query("搜一下 OpenAI 最新新闻")
    assert not is_web_search_query("你好")


def test_strip_rhetorical_prefix_for_github_query() -> None:
    from secretary.agent.web_routing import build_search_query

    query = build_search_query("你会上网查这个信息吗？GitHub 最近一周最火的项目都有哪些？")
    assert "GitHub" in query
    assert "你会上网查" not in query


def test_local_path_lookup_is_not_web_search() -> None:
    assert not is_web_search_query("查一下 ~/Documents/My Projects/ 里有哪些项目")
    assert is_web_search_query("GitHub 最近一周最火的项目都有哪些？")


def test_resolve_web_search_never_blocks_on_missing_location() -> None:
    plan = resolve_web_search("今天天气怎么样")
    assert plan is not None
    assert plan.search_query == "今天天气怎么样"


def test_general_web_search_no_city_suffix() -> None:
    plan = resolve_web_search("搜一下 OpenAI 最新动态", location_city="杭州")
    assert plan is not None
    assert plan.search_query == "搜一下 OpenAI 最新动态"


# ---------------------------------------------------------------------------
# LLM intent router tests
# ---------------------------------------------------------------------------


def test_parse_web_intent_positive_with_query() -> None:
    raw = '{"needs_web": true, "query": "alva.ai", "reason": "product lookup"}'
    needs, query, reason = _parse_web_intent(raw, fallback_query="alva.ai 是什么东西")
    assert needs is True
    assert query == "alva.ai"
    assert reason == "product lookup"


def test_parse_web_intent_positive_without_query_uses_fallback() -> None:
    raw = '{"needs_web": true, "query": "", "reason": "needs web"}'
    needs, query, _ = _parse_web_intent(raw, fallback_query="alva.ai 是什么")
    assert needs is True
    assert query == "alva.ai 是什么"


def test_parse_web_intent_negative() -> None:
    raw = '{"needs_web": false, "query": "", "reason": "chitchat"}'
    needs, query, _ = _parse_web_intent(raw, fallback_query="你好")
    assert needs is False
    assert query == ""


def test_parse_web_intent_fenced_json() -> None:
    raw = '```json\n{"needs_web": true, "query": "OpenAI GPT-5"}\n```'
    needs, query, _ = _parse_web_intent(raw, fallback_query="gpt-5")
    assert needs is True
    assert query == "OpenAI GPT-5"


def test_parse_web_intent_malformed_returns_false() -> None:
    needs, query, _ = _parse_web_intent("not a json at all", fallback_query="x")
    assert needs is False
    assert query == ""


def _make_router_with_llm(
    monkeypatch,
    *,
    llm_response: str,
    llm_available: bool = True,
) -> WebIntentRouter:
    """Build a WebIntentRouter with chat_completion + resolve_llm_config stubbed."""
    settings = Settings()
    if not llm_available:
        monkeypatch.setattr(
            "secretary.agent.llm_config.resolve_llm_config",
            lambda *a, **kw: None,
        )
    else:
        from secretary.agent.llm_config import LlmConfig

        monkeypatch.setattr(
            "secretary.agent.llm_config.resolve_llm_config",
            lambda *a, **kw: LlmConfig(
                api_key="test-key",
                base_url="https://example.com/v1",
                model="test-model",
                source="test",
            ),
        )
    monkeypatch.setattr(
        "secretary.agent.llm_client.chat_completion",
        lambda *a, **kw: llm_response,
    )
    return WebIntentRouter(settings, agent_config_store=None)


def test_router_judges_product_question_as_web(
    monkeypatch,
) -> None:
    """'alva.ai 是什么东西' should be judged as needing web search."""
    llm_response = '{"needs_web": true, "query": "alva.ai", "reason": "product lookup"}'
    router = _make_router_with_llm(monkeypatch, llm_response=llm_response)
    plan = router.judge("alva.ai 是什么东西")
    assert plan is not None
    assert plan.search_query == "alva.ai"


def test_router_judges_chitchat_as_no_web(
    monkeypatch,
) -> None:
    """'你好' should be judged as not needing web search."""
    llm_response = '{"needs_web": false, "query": "", "reason": "greeting"}'
    router = _make_router_with_llm(monkeypatch, llm_response=llm_response)
    plan = router.judge("你好")
    assert plan is None


def test_router_returns_none_when_llm_unavailable(
    monkeypatch,
) -> None:
    """No LLM config → return None, don't raise."""
    router = _make_router_with_llm(
        monkeypatch, llm_response="", llm_available=False
    )
    plan = router.judge("alva.ai 是什么")
    assert plan is None


def test_router_returns_none_on_llm_exception(
    monkeypatch,
) -> None:
    """LLM call raising → return None, don't propagate."""

    def raise_on_call(*a, **kw):
        raise RuntimeError("network down")

    from secretary.agent.llm_config import LlmConfig

    monkeypatch.setattr(
        "secretary.agent.llm_config.resolve_llm_config",
        lambda *a, **kw: LlmConfig(
            api_key="test-key",
            base_url="https://example.com/v1",
            model="test-model",
            source="test",
        ),
    )
    monkeypatch.setattr("secretary.agent.llm_client.chat_completion", raise_on_call)
    router = WebIntentRouter(Settings(), agent_config_store=None)
    plan = router.judge("alva.ai 是什么")
    assert plan is None


def test_resolve_with_llm_fallback_uses_keyword_path_first(
    monkeypatch,
) -> None:
    """Keyword-matched queries must NOT invoke the LLM router."""

    def fail_if_called(*a, **kw):
        raise AssertionError("LLM router should not be called for keyword match")

    class FailingRouter:
        def judge(self, message, history=None):
            fail_if_called()

    # '搜一下 OpenAI 最新动态' hits keyword '搜一下' → should bypass LLM
    plan = resolve_web_search_with_llm_fallback(
        "搜一下 OpenAI 最新动态",
        None,
        llm_router=FailingRouter(),  # type: ignore[arg-type]
    )
    assert plan is not None
    assert plan.search_query == "搜一下 OpenAI 最新动态"


def test_resolve_with_llm_fallback_uses_llm_when_keyword_misses(
    monkeypatch,
) -> None:
    """Keyword-missed queries should fall through to the LLM router."""
    llm_response = '{"needs_web": true, "query": "alva.ai platform"}'
    router = _make_router_with_llm(monkeypatch, llm_response=llm_response)
    plan = resolve_web_search_with_llm_fallback(
        "alva.ai 是什么东西",
        None,
        llm_router=router,
    )
    assert plan is not None
    assert plan.search_query == "alva.ai platform"


def test_resolve_with_llm_fallback_no_router_returns_none() -> None:
    """Without an LLM router, keyword-missed queries return None (original behavior)."""
    plan = resolve_web_search_with_llm_fallback(
        "alva.ai 是什么东西",
        None,
        llm_router=None,
    )
    assert plan is None
