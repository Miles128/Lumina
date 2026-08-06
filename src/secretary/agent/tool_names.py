"""Single source of truth for tool names and Pi↔legacy aliases.

Canonical names follow Pi (``ls`` / ``read`` / ``write`` / ``edit`` / ``grep`` /
``glob``); legacy aliases (``file_read`` / ``patch`` / ``search_files`` …) map to
them. Every subsystem (loop lookup, progress labels, profile allow-lists) must
derive from this module instead of re-declaring alias pairs.
"""

from __future__ import annotations

# legacy name -> canonical name (Pi-aligned)
LEGACY_TO_CANONICAL: dict[str, str] = {
    "file_read": "read",
    "file_write": "write",
    "patch": "edit",
    "list_dir": "ls",
    "search_files": "grep",
    "glob_files": "glob",
    "find": "glob",
}

CANONICAL_TO_LEGACY: dict[str, str] = {
    canonical: legacy for legacy, canonical in LEGACY_TO_CANONICAL.items()
}


def all_tool_aliases(canonical: str) -> tuple[str, ...]:
    """Every name that resolves to ``canonical`` (canonical name first)."""
    return (canonical,) + tuple(
        legacy for legacy, target in LEGACY_TO_CANONICAL.items() if target == canonical
    )


def expand_aliases(names: frozenset[str] | set[str]) -> frozenset[str]:
    """Expand a canonical-name set with every legacy alias that points at it."""
    expanded = set(names)
    for legacy, canonical in LEGACY_TO_CANONICAL.items():
        if canonical in names:
            expanded.add(legacy)
    return frozenset(expanded)


def to_canonical(name: str) -> str:
    return LEGACY_TO_CANONICAL.get(name, name)


# Display labels keyed by canonical name; aliases resolve through to_canonical.
TOOL_LABELS: dict[str, str] = {
    "ls": "浏览目录",
    "read": "读取文件",
    "read_document": "读取文档",
    "write": "写入文件",
    "edit": "编辑文件",
    "move": "移动文件",
    "file_delete": "删除文件",
    "grep": "搜索文件",
    "glob": "查找文件",
    "shell": "执行命令",
    "code_exec": "运行代码",
    "search_memory": "搜索记忆",
    "session_search": "搜索会话",
    "web_search": "联网搜索",
    "web_fetch": "抓取网页",
    "browser_open": "打开网页",
    "browser_snapshot": "浏览器快照",
    "browser_screenshot": "浏览器截图",
    "browser_click": "浏览器点击",
    "browser_fill": "浏览器填写",
    "browser_close": "关闭浏览器",
    "shibei_search": "Shibei 检索",
    "shibei_import": "Shibei 导入",
    "shibei_list_sources": "Shibei 索引",
    "memory": "更新记忆",
    "todo": "待办",
    "skills_list": "列出技能",
    "skill_view": "查看技能",
    "clarify": "澄清问题",
    "ask_user": "询问用户",
    "spawn_subagent": "委派子任务",
    "emit_card": "卡片输出",
}


def tool_label(name: str) -> str:
    """Return the display label for a tool name (aliases resolve to canonical)."""
    return TOOL_LABELS.get(to_canonical(name), "")
