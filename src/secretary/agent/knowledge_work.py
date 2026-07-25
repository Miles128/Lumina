"""Scene appendices and light retries for research / writing / office intents."""

from __future__ import annotations

from secretary.agent.task_intent import TaskIntent, resolve_task_intent

RESEARCH_APPENDIX = """\
## 知识工作 · 调研（本回合）

- 先检索再下结论：优先 **web_search** / **web_fetch**；若已启用 Shibei，个人/笔记向问题先 **shibei_search**（或等价召回）。
- 回复中用脚注编号引用（如 `[^1]`），文末列出简短来源；不要让用户自己去打开链接。
- 至少完成一轮检索工具调用后再作答；信息不足时说明缺口，勿编造出处。"""

WRITING_APPENDIX = """\
## 知识工作 · 写作（本回合）

- 先给出标题与简短大纲，再写正文（用户只要片段时可省略大纲）。
- **不要**调用 write / edit，除非用户明确要求保存到路径或文件名。
- 可使用用户粘贴素材、记忆或 Shibei；引用须有依据，禁止虚构「根据你的笔记」。"""

OFFICE_APPENDIX = """\
## 知识工作 · 办公文档（本回合）

- 涉及本地文档时优先 **read_document**（Office 二进制）或 **read**（文本），再整理要点。
- 输出结构化结果：纪要 / 要点清单 / 表格摘要 / 邮件草稿等，匹配用户请求。
- 写回磁盘仅在用户给出路径或明确「保存到/写入…」时使用 write / edit。"""

RESEARCH_RETRY_USER = (
    "[System] 上一轮未完成调研检索就下了结论。"
    "请先调用 web_search / web_fetch 或 shibei_search（若可用）获取依据，"
    "再用脚注引用后回答；禁止让用户自己去查。"
)

OFFICE_RETRY_USER = (
    "[System] 上一轮讨论了文档内容但未打开文档。"
    "请先调用 read_document 或 read 读取用户提到的文件，再基于工具返回整理要点。"
)

_RETRIEVAL_TOOLS = frozenset(
    {
        "web_search",
        "web_fetch",
        "shibei_search",
        "search_memory",
        "browser_open",
        "browser_snapshot",
    }
)

_DOC_READ_TOOLS = frozenset({"read_document", "read", "file_read"})

_SOURCE_CLAIM_MARKERS = (
    "根据",
    "业界",
    "研究表明",
    "通常",
    "常用",
    "据说",
    "有人认为",
    "指标",
    "结论",
)


def intent_system_appendix(intent: TaskIntent) -> str:
    if intent is TaskIntent.RESEARCH:
        return "\n\n" + RESEARCH_APPENDIX
    if intent is TaskIntent.WRITING:
        return "\n\n" + WRITING_APPENDIX
    if intent is TaskIntent.OFFICE:
        return "\n\n" + OFFICE_APPENDIX
    return ""


def should_retry_for_research_intent(
    user_message: str,
    reply: str,
    used_tools: list[str],
) -> bool:
    if resolve_task_intent(user_message) is not TaskIntent.RESEARCH:
        return False
    if any(name in _RETRIEVAL_TOOLS for name in used_tools):
        return False
    text = (reply or "").strip()
    if not text:
        return False
    return any(marker in text for marker in _SOURCE_CLAIM_MARKERS)


def should_retry_for_office(
    user_message: str,
    reply: str,
    used_tools: list[str],
) -> bool:
    if resolve_task_intent(user_message) is not TaskIntent.OFFICE:
        return False
    if any(name in _DOC_READ_TOOLS for name in used_tools):
        return False
    # Also accept MCP content-read style tools.
    if any(
        name.startswith("mcp_") and any(h in name.lower() for h in ("read", "get_file"))
        for name in used_tools
    ):
        return False
    text = (reply or "").strip()
    if len(text) < 8:
        return False
    return True
