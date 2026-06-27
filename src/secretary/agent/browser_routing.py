"""When to expose browser_* tools alongside web_search / web_fetch."""

from __future__ import annotations

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
    "榜单",
    "trending",
    "涨星",
    "星星",
    "github.com",
    "gitlab.com",
)


def needs_browser_tools(message: str) -> bool:
    """Full / web routes: offer browser_* when page likely needs a real browser."""
    if not agent_browser_available():
        return False
    cleaned = message.strip()
    if not cleaned:
        return False
    if is_web_search_query(cleaned):
        return True
    lowered = cleaned.lower()
    return any(marker in cleaned or marker in lowered for marker in _DYNAMIC_BROWSER_MARKERS)
