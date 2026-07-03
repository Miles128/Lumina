"""When to expose browser_* tools alongside web_search / web_fetch."""

from __future__ import annotations

from secretary.agent.agent_profile import AgentProfile
from secretary.agent.browser_tools import agent_browser_available
from secretary.agent.web_routing import is_web_search_query

_DYNAMIC_BROWSER_MARKERS = (
    "动态",
    "js渲染",
    "javascript",
    "单页",
    "spa",
    "登录",
    "登陆",
    "需要登录",
    "点击",
    "填表",
    "表单",
    "验证码",
    "截图",
    "screenshot",
    "榜单",
    "trending",
    "涨星",
    "星星",
    "github.com",
    "gitlab.com",
)

_RESEARCH_MARKERS = (
    "research",
    "调研",
    "查一下",
    "帮我查",
    "搜索",
    "搜一下",
    "打开网页",
    "访问",
    "浏览",
    "官网",
)


def needs_browser_tools(message: str, *, profile: AgentProfile | None = None) -> bool:
    """Offer browser_* when the page likely needs a real browser."""
    if not agent_browser_available():
        return False
    cleaned = message.strip()
    if not cleaned:
        return False
    if is_web_search_query(cleaned):
        return True
    lowered = cleaned.lower()
    if any(marker in cleaned or marker in lowered for marker in _DYNAMIC_BROWSER_MARKERS):
        return True
    if profile in {AgentProfile.ASK, AgentProfile.PLAN}:
        return any(marker in cleaned or marker in lowered for marker in _RESEARCH_MARKERS)
    return False
