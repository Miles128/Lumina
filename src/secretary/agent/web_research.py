"""Generic web-research instructions for the agent loop (no per-site hardcoding)."""

from __future__ import annotations

import re

WEB_RESEARCH_APPENDIX = """\
## 联网检索（本回合）

- 实时、榜单、新闻、价格、天气等：用 **web_search** 获取摘要；若结果明显跑题、过旧或只有二手文章，**换关键词再搜**（可试英文），不要一次失败就放弃。
- 需要一手数据时：用 **web_fetch** 打开搜索结果里的**官方/原始页面**（平台自带的 trending / 排行榜 / 文档页），再整理成答案。
- **禁止**说「建议你直接访问」「自己去某某页面看」或只贴链接不总结；你必须根据工具返回写出可读结论。
- 至少完成：**一次 web_search + 一次 web_fetch**（或两次不同关键词的 web_search），再回复用户。
- 抓取 `https://github.com/trending` 时会自动解析列表；若页面不可用会回退 GitHub Search API，请直接根据工具输出列仓库，不要说「页面是 JS 渲染抓不到」。

## 引用格式（重要）

- 回复中引用来源时，**用脚注编号**（如 `[^1]`、`[^2]`），**不要**在正文里贴完整 URL。
- 在回复末尾用脚注列出来源，每条一行，格式：`[^1]: 标题或域名`（不写 `https://` 前缀和长路径，只保留域名+简短路径，例如 `example.com/news/gpt5`）。
- 正文提及来源时写 `根据[^1]` 或在句尾标 `[^1]`，不要写「详见 https://...」。
- 禁止把完整 URL 作为正文的一部分；URL 只能出现在末尾脚注里且必须是简短形式。"""

BROWSER_TOOL_GUIDANCE = """\
## 浏览器工具（agent-browser，与 web_fetch 分工）

- **静态页 / 官方 API / 已能解析的 HTML**：优先 `web_fetch`（更快）。
- **JS 渲染、登录后内容、web_fetch 只有导航骨架**：`browser_open` → `browser_snapshot` → 用 `@e1` 等 ref 做 `browser_click` / `browser_fill`。
- 流程建议：web_search 找 URL → web_fetch 试一手 → 不够再 browser_open 同一 URL → snapshot 读列表/正文 → 完成后可 `browser_close`。
- 禁止未 snapshot 就瞎猜页面内容；禁止让用户自己去浏览器里操作。"""

WEB_RETRY_USER = (
    "[System] 上一轮回复不合格：只给了链接、让用户自己去看，或声称搜不到榜单。"
    "你必须在本轮内继续联网：先 web_fetch 打开结果或官方榜单/排行榜 URL，"
    "或换英文/更窄关键词再 web_search。"
    "禁止再次让用户自己去打开网页；只能根据工具返回写结论。"
)

_PUNT_MARKERS = (
    "建议你直接访问",
    "建议你访问",
    "建议直接访问",
    "自己去",
    "自行访问",
    "请访问以下",
    "打开以下页面",
    "无法直接列出",
    "没有直接给出",
    "没有直接提供",
    "无法直接提供",
    "返回的主要是旧文章",
    "搜不到",
)

_PUNT_URL_RE = re.compile(
    r"https?://[^\s\)\]\"']+(?:trending|search\?)[^\s\)\]\"']*",
    re.IGNORECASE,
)


def reply_punts_to_user_browsing(reply: str) -> bool:
    text = reply.strip()
    if not text:
        return False
    if any(marker in text for marker in _PUNT_MARKERS):
        return True
    if _PUNT_URL_RE.search(text) and len(text) < 1200:
        link_lines = len(_PUNT_URL_RE.findall(text))
        if link_lines >= 1 and ("建议" in text or "访问" in text or "抱歉" in text):
            return True
    return False


def should_retry_for_web_research(
    user_message: str,
    reply: str,
    used_tools: list[str],
) -> bool:
    from secretary.agent.web_routing import is_web_search_query

    if not is_web_search_query(user_message):
        return False
    if reply_punts_to_user_browsing(reply):
        return True
    used = set(used_tools)
    if "web_fetch" not in used and "web_search" in used:
        if re.search(r"抱歉|无法|没有.{0,8}(结果|榜单|数据)", reply):
            return True
    if used == {"web_search"} or used_tools.count("web_search") == 1:
        if "web_fetch" not in used and re.search(r"抱歉|建议|无法", reply):
            return True
    return False


# Root tokens that signal search/fetch intent in a short reply.
# We match roots (not full phrases) because LLM wording is open-ended —
# "联网抓一下一手资料" / "我去找找看" / "帮你带引用" all slip past a
# fixed phrase list.  A root-token pre-filter catches them all.
_SEARCH_INTENT_ROOTS = (
    "搜",
    "查",
    "抓",
    "找",
    "检索",
    "联网",
    "上网",
    "资料",
    "引用",
    "来源",
    "链接",
    "一手",
    "最新",
    "实时",
)

_WEB_TOOL_NAMES = frozenset({"web_search", "web_fetch"})


def reply_claims_web_search(reply: str, used_tools: list[str]) -> bool:
    """LLM shows search intent but no web tool was actually called this turn.

    Catches the failure mode where the model writes '让我搜一下' / '我联网抓一下
    一手资料' / '帮你带引用' as text without emitting a tool_call, then the turn
    would end with an empty or hallucinated answer.

    Uses root-token matching instead of a fixed phrase list: LLM wording is
    open-ended, so enumerating complete phrases is a losing game.  Any short
    reply (< 200 chars) that contains a search-intent root token and wasn't
    backed by an actual web tool call triggers a forced injection.
    """
    if any(name in _WEB_TOOL_NAMES for name in used_tools):
        return False
    text = reply.strip()
    if not text or len(text) > 200:
        return False
    return any(root in text for root in _SEARCH_INTENT_ROOTS)
