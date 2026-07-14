"""FR-29: Tavily / Brave / Bocha search API providers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from secretary.agent.web_search import (
    SearchResult,
    fallback_engine_order,
    run_search,
)
from secretary.agent.web_search_providers import (
    configured_api_engines,
    parse_bocha_response,
    parse_brave_response,
    parse_tavily_response,
    search_bocha,
    search_brave,
    search_tavily,
)


def test_parse_tavily_response() -> None:
    payload = {
        "results": [
            {
                "title": "Messi",
                "url": "https://example.com/messi",
                "content": "Argentine footballer",
            }
        ]
    }
    results = parse_tavily_response(payload, limit=5)
    assert len(results) == 1
    assert results[0].engine == "tavily"
    assert results[0].title == "Messi"
    assert "Argentine" in results[0].snippet


def test_parse_brave_response() -> None:
    payload = {
        "web": {
            "results": [
                {
                    "title": "OpenAI",
                    "url": "https://openai.com",
                    "description": "AI research",
                }
            ]
        }
    }
    results = parse_brave_response(payload, limit=5)
    assert len(results) == 1
    assert results[0].engine == "brave"
    assert results[0].url == "https://openai.com"


def test_parse_bocha_response() -> None:
    payload = {
        "data": {
            "webPages": {
                "value": [
                    {
                        "name": "阿里巴巴 ESG",
                        "url": "https://example.com/esg",
                        "snippet": "摘要一",
                        "summary": "长摘要",
                    }
                ]
            }
        }
    }
    results = parse_bocha_response(payload, limit=5)
    assert len(results) == 1
    assert results[0].engine == "bocha"
    assert results[0].title == "阿里巴巴 ESG"
    assert "长摘要" in results[0].snippet or "摘要" in results[0].snippet


def test_configured_api_engines_reads_env() -> None:
    with patch.dict(
        "os.environ",
        {"TAVILY_API_KEY": "tvly-x", "BRAVE_API_KEY": "", "BOCHA_API_KEY": "sk-bocha"},
        clear=False,
    ):
        # Clear empty brave by ensuring blank is ignored
        engines = configured_api_engines()
    assert "tavily" in engines
    assert "bocha" in engines
    assert "brave" not in engines


def test_fallback_prefers_api_when_configured_chinese() -> None:
    with patch(
        "secretary.agent.web_search.configured_api_engines",
        return_value=("bocha", "tavily"),
    ):
        order = fallback_engine_order(None, "杭州天气")
    assert order[0] == "bocha"
    assert "bing" in order


def test_fallback_prefers_tavily_for_english_when_configured() -> None:
    with patch(
        "secretary.agent.web_search.configured_api_engines",
        return_value=("tavily", "brave", "bocha"),
    ):
        order = fallback_engine_order(None, "OpenAI news")
    assert order[0] == "tavily"


def test_search_tavily_posts_json() -> None:
    payload = {
        "results": [
            {"title": "A", "url": "https://a.example", "content": "alpha"},
        ]
    }
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    client = MagicMock()
    client.post.return_value = response
    client_cm = MagicMock()
    client_cm.__enter__.return_value = client

    with patch("secretary.agent.web_search_providers.httpx.Client", return_value=client_cm):
        results = search_tavily("query", 3, api_key="tvly-test")

    assert len(results) == 1
    assert results[0].engine == "tavily"
    assert client.post.call_args[0][0] == "https://api.tavily.com/search"
    body = client.post.call_args.kwargs["json"]
    assert body["query"] == "query"
    assert body["api_key"] == "tvly-test"


def test_search_brave_uses_subscription_header() -> None:
    payload = {
        "web": {
            "results": [
                {"title": "B", "url": "https://b.example", "description": "bravo"},
            ]
        }
    }
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    client = MagicMock()
    client.get.return_value = response
    client_cm = MagicMock()
    client_cm.__enter__.return_value = client

    with patch("secretary.agent.web_search_providers.httpx.Client", return_value=client_cm):
        results = search_brave("query", 3, api_key="brave-key")

    assert results[0].engine == "brave"
    headers = client.get.call_args.kwargs["headers"]
    assert headers["X-Subscription-Token"] == "brave-key"


def test_search_bocha_uses_bearer() -> None:
    payload = {
        "data": {
            "webPages": {
                "value": [
                    {"name": "C", "url": "https://c.example", "snippet": "charlie"},
                ]
            }
        }
    }
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    client = MagicMock()
    client.post.return_value = response
    client_cm = MagicMock()
    client_cm.__enter__.return_value = client

    with patch("secretary.agent.web_search_providers.httpx.Client", return_value=client_cm):
        results = search_bocha("query", 3, api_key="bocha-key")

    assert results[0].engine == "bocha"
    headers = client.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer bocha-key"


def test_run_search_uses_tavily_engine() -> None:
    hit = [SearchResult(title="T", url="https://t.example", snippet="s", engine="tavily")]

    with patch("secretary.agent.web_search._API_ENGINES", {"tavily": lambda q, n: hit}):
        with patch(
            "secretary.agent.web_search.configured_api_engines",
            return_value=("tavily",),
        ):
            results, engine = run_search("Python", "tavily", 3)

    assert engine == "tavily"
    assert results[0].title == "T"


def test_run_search_unknown_api_engine_still_raises_without_key() -> None:
    with patch("secretary.agent.web_search.configured_api_engines", return_value=()):
        with pytest.raises(ValueError, match="unknown engine"):
            run_search("Python", "tavily", 3)


def test_parse_serper_response() -> None:
    from secretary.agent.web_search_providers import parse_serper_response

    payload = {
        "organic": [
            {"title": "Serper Hit", "link": "https://serper.example", "snippet": "google via serper"},
        ]
    }
    results = parse_serper_response(payload, limit=5)
    assert len(results) == 1
    assert results[0].engine == "serper"
    assert results[0].url == "https://serper.example"


def test_parse_serpapi_response() -> None:
    from secretary.agent.web_search_providers import parse_serpapi_response

    payload = {
        "organic_results": [
            {"title": "SerpAPI Hit", "link": "https://serpapi.example", "snippet": "organic"},
        ]
    }
    results = parse_serpapi_response(payload, limit=5)
    assert results[0].engine == "serpapi"
    assert "organic" in results[0].snippet


def test_parse_bing_api_response() -> None:
    from secretary.agent.web_search_providers import parse_bing_api_response

    payload = {
        "webPages": {
            "value": [
                {"name": "Bing API", "url": "https://bing-api.example", "snippet": "azure"},
            ]
        }
    }
    results = parse_bing_api_response(payload, limit=5)
    assert results[0].engine == "bing_api"
    assert results[0].title == "Bing API"


def test_parse_perplexity_response() -> None:
    from secretary.agent.web_search_providers import parse_perplexity_response

    payload = {
        "search_results": [
            {
                "title": "Pplx",
                "url": "https://pplx.example",
                "snippet": "sonar result",
            }
        ],
        "citations": ["https://cite.example"],
    }
    results = parse_perplexity_response(payload, limit=5)
    assert results[0].engine == "perplexity"
    assert results[0].url == "https://pplx.example"


def test_search_serper_posts_with_api_key_header() -> None:
    from secretary.agent.web_search_providers import search_serper

    payload = {"organic": [{"title": "S", "link": "https://s.example", "snippet": "x"}]}
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    client = MagicMock()
    client.post.return_value = response
    client_cm = MagicMock()
    client_cm.__enter__.return_value = client

    with patch("secretary.agent.web_search_providers.httpx.Client", return_value=client_cm):
        results = search_serper("q", 3, api_key="serper-key")

    assert results[0].engine == "serper"
    assert client.post.call_args[0][0] == "https://google.serper.dev/search"
    assert client.post.call_args.kwargs["headers"]["X-API-KEY"] == "serper-key"


def test_search_serpapi_get() -> None:
    from secretary.agent.web_search_providers import search_serpapi

    payload = {
        "organic_results": [{"title": "R", "link": "https://r.example", "snippet": "y"}],
    }
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    client = MagicMock()
    client.get.return_value = response
    client_cm = MagicMock()
    client_cm.__enter__.return_value = client

    with patch("secretary.agent.web_search_providers.httpx.Client", return_value=client_cm):
        results = search_serpapi("q", 3, api_key="serp-key")

    assert results[0].engine == "serpapi"
    params = client.get.call_args.kwargs["params"]
    assert params["api_key"] == "serp-key"
    assert params["q"] == "q"


def test_search_bing_api_subscription_header() -> None:
    from secretary.agent.web_search_providers import search_bing_api

    payload = {
        "webPages": {
            "value": [{"name": "B", "url": "https://b.example", "snippet": "z"}],
        }
    }
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    client = MagicMock()
    client.get.return_value = response
    client_cm = MagicMock()
    client_cm.__enter__.return_value = client

    with patch("secretary.agent.web_search_providers.httpx.Client", return_value=client_cm):
        results = search_bing_api("q", 3, api_key="bing-key")

    assert results[0].engine == "bing_api"
    headers = client.get.call_args.kwargs["headers"]
    assert headers["Ocp-Apim-Subscription-Key"] == "bing-key"


def test_search_perplexity_chat_completions() -> None:
    from secretary.agent.web_search_providers import search_perplexity

    payload = {
        "search_results": [
            {"title": "P", "url": "https://p.example", "snippet": "sonar"},
        ]
    }
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    client = MagicMock()
    client.post.return_value = response
    client_cm = MagicMock()
    client_cm.__enter__.return_value = client

    with patch("secretary.agent.web_search_providers.httpx.Client", return_value=client_cm):
        results = search_perplexity("q", 3, api_key="pplx-key")

    assert results[0].engine == "perplexity"
    assert client.post.call_args[0][0] == "https://api.perplexity.ai/chat/completions"
    assert client.post.call_args.kwargs["headers"]["Authorization"] == "Bearer pplx-key"


def test_api_preference_includes_reserved_engines() -> None:
    from secretary.agent.web_search_providers import api_preference_order

    order = api_preference_order(
        "OpenAI news",
        ("serper", "serpapi", "bing_api", "perplexity", "tavily"),
    )
    assert order[0] == "tavily"
    assert "serper" in order
    assert "bing_api" in order
    assert "perplexity" in order
