"""Soft task intents for knowledge-work routing (orthogonal to AgentProfile)."""

from __future__ import annotations

import re
from enum import StrEnum

from secretary.agent.grounding import is_memory_write_request


class TaskIntent(StrEnum):
    RESEARCH = "research"
    WRITING = "writing"
    OFFICE = "office"
    CODE = "code"
    NONE = "none"


_RESEARCH_MARKERS = (
    "调研",
    "查资料",
    "深度研究",
    "做研究",
    "研究报告",
    "有哪些说法",
    "对比一下",
    "对比分析",
    "文献",
    "评测指标",
    "research",
    "investigate",
)

_WRITING_MARKERS = (
    "写一篇",
    "写一篇文章",
    "写文章",
    "写短文",
    "润色",
    "改写",
    "扩写",
    "起草",
    "提纲",
    "写大纲",
    "成稿",
    "写报告",
    "写一份报告",
    "写篇",
    "帮我写",
    "请写",
    "draft",
    "rewrite",
    "proofread",
)

_WRITING_PLAN_MARKERS = (
    "大纲",
    "结构",
    "章节",
    "提纲",
    "目录结构",
)

_OFFICE_MARKERS = (
    "会议纪要",
    "纪要",
    "邮件草稿",
    "写邮件",
    "表格汇总",
    "整理表格",
    "pptx",
    "xlsx",
    "docx",
    "pdf",
    ".pptx",
    ".xlsx",
    ".docx",
    ".pdf",
    "幻灯片",
    "spreadsheet",
)

_OFFICE_FILE_RE = re.compile(
    r"\b[\w./~-]+\.(?:docx|pdf|xlsx|pptx|doc|xls|ppt)\b",
    re.IGNORECASE,
)

_CODE_MARKERS = (
    "重构",
    "refactor",
    "patch",
    "shell",
    "git commit",
    "运行测试",
    "修 bug",
    "修bug",
    "bugfix",
    "code_exec",
    "spawn",
    "委派",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".go",
    ".rs",
)

_PERSIST_MARKERS = (
    "保存到",
    "保存为",
    "写到",
    "写入",
    "写进",
    "覆盖",
    "生成到",
    "输出到",
    "落到",
    "落盘",
    "save to",
    "write to",
    "save as",
)

_FILENAME_OR_PATH_RE = re.compile(
    r"(?:~/[^\s\"'`]+|"
    r"/Users/[^\s\"'`]+|"
    r"(?:\./|\../)[^\s\"'`]+|"
    r"\b[\w./-]+\.[A-Za-z0-9]{1,8}\b|"
    r"`[^`]+`)",
    re.IGNORECASE,
)

_MUTATE_MARKERS = (
    "改一下",
    "删掉",
    "删除",
    "创建文件",
    "运行",
    "执行命令",
    "同步",
    "部署",
    "安装",
    "构建",
    "git ",
    "npm ",
    "pytest",
    "file_write",
    "write",
    "edit",
    "file_delete",
)


def has_persist_signal(message: str) -> bool:
    """True when user asks to write/save to a file path or filename."""
    text = message.strip()
    if not text:
        return False
    if is_memory_write_request(text):
        return False
    lowered = text.lower()
    if not any(marker in text or marker in lowered for marker in _PERSIST_MARKERS):
        return False
    return bool(_FILENAME_OR_PATH_RE.search(text))


def has_code_mutate_signal(message: str) -> bool:
    text = message.strip()
    if not text:
        return False
    lowered = text.lower()
    if any(marker in text or marker in lowered for marker in _MUTATE_MARKERS):
        return True
    if any(marker in text or marker in lowered for marker in _CODE_MARKERS):
        # Bare .py in "写一篇关于 .py 的文章" — require code-ish verbs or path mutate
        if any(
            marker in text or marker in lowered
            for marker in (
                "重构",
                "refactor",
                "修",
                "bug",
                "patch",
                "shell",
                "测试",
                "运行",
                "执行",
                "commit",
                "spawn",
                "委派",
                "code_exec",
            )
        ):
            return True
        if re.search(r"\b\w+\.(?:py|ts|tsx|js|go|rs)\b", text, re.IGNORECASE) and any(
            m in text for m in ("改", "修", "重构", "跑", "测")
        ):
            return True
    return False


def is_writing_plan_request(message: str) -> bool:
    text = message.strip()
    if not text:
        return False
    if resolve_task_intent(text) is not TaskIntent.WRITING:
        return False
    return any(marker in text for marker in _WRITING_PLAN_MARKERS) and any(
        marker in text for marker in ("规划", "方案", "计划", "怎么安排", "如何组织")
    )


def resolve_task_intent(message: str) -> TaskIntent:
    """Rule-based intent; priority documented in the design spec."""
    text = message.strip()
    if not text:
        return TaskIntent.NONE
    lowered = text.lower()

    persist = has_persist_signal(text)
    codeish = has_code_mutate_signal(text)

    research_hit = any(m in text or m in lowered for m in _RESEARCH_MARKERS)
    writing_hit = any(m in text or m in lowered for m in _WRITING_MARKERS)
    office_hit = any(m in text or m in lowered for m in _OFFICE_MARKERS) or bool(
        _OFFICE_FILE_RE.search(text)
    )

    # Persist + office/writing keeps scene intent (profile becomes Build separately).
    if codeish and not writing_hit and not office_hit and not research_hit:
        return TaskIntent.CODE
    if codeish and re.search(r"\b\w+\.(?:py|ts|tsx|js|go|rs)\b", text, re.IGNORECASE):
        if not writing_hit and not research_hit and not office_hit:
            return TaskIntent.CODE

    if research_hit:
        return TaskIntent.RESEARCH
    if writing_hit and not office_hit:
        return TaskIntent.WRITING
    if writing_hit and office_hit and persist:
        # e.g. 把纪要写入 minutes.md — office write-back
        return TaskIntent.OFFICE
    if writing_hit and office_hit:
        return TaskIntent.WRITING
    if office_hit:
        return TaskIntent.OFFICE
    if codeish:
        return TaskIntent.CODE
    if persist:
        # Save/write-to-path without stronger scene markers → prose/file drafting.
        return TaskIntent.WRITING
    return TaskIntent.NONE
