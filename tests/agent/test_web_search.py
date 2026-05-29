from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from secretary.agent.web_search import (
    WebSearchTool,
    _ENGINES,
    _baidu,
    _bing,
    _ddg,
    _decode_bing_url,
    _sogou,
    run_search,
    SearchResult,
)

BING_HTML = """
<ol>
<li class="b_algo" data-id="1">
  <h2><a href="https://www.bing.com/ck/a?!&amp;&amp;u=a1aHR0cHM6Ly93d3cucnVub29iLmNvbS9weXRob24v">Python 基础教程 | 菜鸟教程</a></h2>
  <div class="b_caption"><p>本教程适合想从零开始学习 Python 的开发人员。</p></div>
</li>
<li class="b_algo" data-id="2">
  <h2><a href="https://www.bing.com/ck/a?!&amp;&amp;u=a1aHR0cHM6Ly9kb2NzLnB5dGhvbi5vcmcvemgtY24vMw==">Python 教程 — Python 文档</a></h2>
  <div class="b_caption"><p>官方中文文档。</p></div>
</li>
</ol>
"""

DDG_HTML = """
<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com">Example Site</a>
<a class="result__snippet">An example search result.</a>
"""

DDG_CAPTCHA_HTML = """
<div class="anomaly-modal__title">Unfortunately, bots use DuckDuckGo too.</div>
"""

BAIDU_CAPTCHA_HTML = """
<script>location.replace("https://wappass.baidu.com/static/captcha/")</script>
"""

SOGOU_ANTISPIDER_HTML = """
<html><head><title>搜狗搜索</title></head><body>antispider</body></html>
"""


def test_decode_bing_url() -> None:
    href = "https://www.bing.com/ck/a?!&&u=a1aHR0cHM6Ly93d3cucnVub29iLmNvbS9weXRob24v"
    assert _decode_bing_url(href) == "https://www.runoob.com/python/"


def test_bing_parser_extracts_results() -> None:
    with patch("secretary.agent.web_search._fetch_html", return_value=BING_HTML):
        results = _bing("Python教程", 5)

    assert len(results) == 2
    assert results[0].title == "Python 基础教程 | 菜鸟教程"
    assert results[0].url == "https://www.runoob.com/python/"
    assert "开发人员" in results[0].snippet
    assert results[0].engine == "bing"


def test_ddg_parser_extracts_results() -> None:
    with patch("secretary.agent.web_search._fetch_html", return_value=DDG_HTML):
        results = _ddg("example", 3)

    assert len(results) == 1
    assert results[0].title == "Example Site"
    assert results[0].url == "https://example.com"
    assert results[0].snippet == "An example search result."


def test_ddg_captcha_returns_empty() -> None:
    with patch("secretary.agent.web_search._fetch_html", return_value=DDG_CAPTCHA_HTML):
        assert _ddg("blocked", 3) == []


def test_baidu_captcha_returns_empty() -> None:
    with patch("secretary.agent.web_search._fetch_html", return_value=BAIDU_CAPTCHA_HTML):
        assert _baidu("blocked", 3) == []


def test_sogou_antispider_returns_empty() -> None:
    with patch("secretary.agent.web_search._fetch_html", return_value=SOGOU_ANTISPIDER_HTML):
        assert _sogou("blocked", 3) == []


def test_run_search_falls_back_when_primary_empty() -> None:
    def empty_ddg(query: str, limit: int) -> list[SearchResult]:
        return []

    def bing_hit(query: str, limit: int) -> list[SearchResult]:
        return [SearchResult(title="Bing hit", url="https://example.com", snippet="", engine="bing")]

    with patch.dict(_ENGINES, {"duckduckgo": empty_ddg, "bing": bing_hit}):
        results, engine = run_search("Python", "duckduckgo", 3)

    assert engine == "bing"
    assert len(results) == 1
    assert results[0].title == "Bing hit"


def test_web_search_tool_uses_fallback(tmp_path: Path) -> None:
    tool = WebSearchTool()

    def empty_ddg(query: str, limit: int) -> list[SearchResult]:
        return []

    def bing_hit(query: str, limit: int) -> list[SearchResult]:
        return [SearchResult(title="教程", url="https://example.com", snippet="简介", engine="bing")]

    with patch.dict(_ENGINES, {"duckduckgo": empty_ddg, "bing": bing_hit}):
        output = tool.execute({"query": "Python", "engine": "duckduckgo"}, tmp_path)

    assert "教程" in output
    assert "via bing" in output


def test_run_search_unknown_engine_raises() -> None:
    with pytest.raises(ValueError, match="unknown engine"):
        run_search("Python", "yahoo", 3)
