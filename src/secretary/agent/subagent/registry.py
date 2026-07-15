"""Archetype definitions: tool sets and sub-agent system prompts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from secretary.agent.p0_tools import PatchTool, SearchFilesTool
from secretary.agent.subagent.custom import load_custom_archetypes
from secretary.agent.subagent.policy import (
    BUILTIN_ARCHETYPES,
    EXPLORE_MAX_STEPS,
    PLAN_MAX_STEPS,
    REFLECT_MAX_STEPS,
    VERIFY_MAX_STEPS,
    WORKER_MAX_STEPS,
)
from secretary.agent.tools.base import Tool
from secretary.agent.tools.fs import FileReadTool, FileWriteTool, ListDirTool
from secretary.agent.tools.memory_tools import SearchMemoryTool, SessionSearchTool
from secretary.agent.tools.shell import ShellTool
from secretary.agent.tools.web import WebFetchTool
from secretary.agent.web_search import WebSearchTool

if TYPE_CHECKING:
    from secretary.agent.subagent.runner import SubAgentDeps


@dataclass(frozen=True)
class ArchetypeSpec:
    name: str
    max_steps: int
    system_prompt: str
    tool_names: frozenset[str] | None = None


EXPLORE_PROMPT = (
    "You are a read-only research sub-agent for Lumina.\n"
    "Use list_dir, file_read, read_document, search_files, search_memory, web_search, "
    "web_fetch, and session_search as needed.\n"
    "Do not modify files or spawn other agents.\n"
    "Report findings as concise bullet points; include file paths when relevant.\n"
    "Do not output internal reasoning chains or step-by-step meta commentary."
)

WORKER_PROMPT = (
    "You are a worker sub-agent for Lumina.\n"
    "You may read and modify the workspace using file_write, patch, shell, and code_exec.\n"
    "Use read_document for Excel/PDF/Word. Destructive or risky operations may pause "
    "for user confirmation.\n"
    "Do not spawn other agents. Return a concise summary of what you changed or found."
)

VERIFY_PROMPT = (
    "You are a verification sub-agent for Lumina (read-only).\n"
    "Review the task using list_dir, file_read, read_document, search_files, "
    "and search_memory.\n\n"
    "Success criteria must be machine-verifiable. Check:\n"
    "- If a test was expected: does it exist and pass? (run shell if needed to verify)\n"
    "- If a file was expected: does it exist with the expected content?\n"
    "- If a function was expected: can you find it in the codebase?\n"
    "- Vague criteria like 'works' or 'looks good' are NOT acceptable — specify what to check.\n\n"
    "Output format:\n"
    "1. Pass/Fail\n"
    "2. Criteria checked (list each criterion and its result)\n"
    "3. Issues found (if any)\n"
    "4. Suggested fixes (if any)\n"
    "Do not modify files or spawn other agents."
)

REFLECT_PROMPT = (
    "You are a reflection agent for Lumina (read-only).\n"
    "Your job: analyze a failed turn and produce a structured lesson for future turns.\n\n"
    "You have read-only tools. Use them ONLY if needed to confirm a specific fact "
    "(e.g., read a file that was patched wrong). Do not explore broadly — max 4 steps.\n\n"
    "Input context will include:\n"
    "- failure_mode: why this turn was flagged as failed\n"
    "- user_message: what the user wanted\n"
    "- raw_reply: what the LLM produced\n"
    "- tool_calls_summary: tools invoked and their outcomes\n"
    "- verify_issues: (if applicable) issues found by verify sub-agent\n\n"
    "Output STRICT JSON, nothing else:\n"
    "{\n"
    '  "failure_summary": "一句话总结失败本质（≤120 字符）",\n'
    '  "root_cause": "根本原因（≤300 字符）",\n'
    '  "lesson": "可迁移的教训，未来类似场景应如何避免（≤300 字符）",\n'
    '  "related_files": ["相关文件路径（如有）"],\n'
    '  "failure_tags": ["1-3 个标签，如 patch_error, shell_failure, scope_creep, wrong_abstraction"]\n'
    "}\n\n"
    "Rules:\n"
    '- Be specific, not generic. "应更仔细" is useless; '
    '"patch 前应先用 search_files 确认函数签名" is useful.\n'
    "- Focus on actionable lessons, not blame.\n"
    '- If the failure is genuinely uninformative (e.g., user just changed mind), '
    'output {"failure_summary": "non-informative", "root_cause": "", "lesson": "", '
    '"related_files": [], "failure_tags": []} and we will skip saving.\n'
    "Do not modify files or spawn other agents."
)

PLAN_SUB_PROMPT = (
    "You are a planning sub-agent for Lumina (read-only).\n"
    "Survey the workspace with list_dir, file_read, read_document, search_files, "
    "and search_memory.\n"
    "Produce a structured plan: goals, steps, risks, and what worker/explore should do next.\n"
    "Do not modify files, run shell, or spawn other agents."
)

def list_archetype_names(lumina_dir: Path | None = None) -> list[str]:
    names = sorted(BUILTIN_ARCHETYPES)
    if lumina_dir is not None:
        custom = load_custom_archetypes(lumina_dir / "subagents")
        names.extend(sorted(custom))
    return names


def get_archetype(name: str, lumina_dir: Path | None = None) -> ArchetypeSpec | None:
    normalized = name.strip().lower()
    if not normalized:
        return None
    if lumina_dir is not None:
        custom = load_custom_archetypes(lumina_dir / "subagents").get(normalized)
        if custom is not None:
            return ArchetypeSpec(
                name=custom.name,
                max_steps=custom.max_steps,
                system_prompt=custom.system_prompt,
                tool_names=custom.tool_names,
            )
    if normalized == "explore":
        return ArchetypeSpec(name="explore", max_steps=EXPLORE_MAX_STEPS, system_prompt=EXPLORE_PROMPT)
    if normalized == "worker":
        return ArchetypeSpec(
            name="worker",
            max_steps=WORKER_MAX_STEPS,
            system_prompt=WORKER_PROMPT,
            tool_names=frozenset(
                {
                    "list_dir",
                    "file_read",
                    "read_document",
                    "search_files",
                    "search_memory",
                    "web_search",
                    "web_fetch",
                    "session_search",
                    "file_write",
                    "patch",
                    "shell",
                    "code_exec",
                }
            ),
        )
    if normalized == "verify":
        return ArchetypeSpec(name="verify", max_steps=VERIFY_MAX_STEPS, system_prompt=VERIFY_PROMPT)
    if normalized == "reflect":
        return ArchetypeSpec(
            name="reflect",
            max_steps=REFLECT_MAX_STEPS,
            system_prompt=REFLECT_PROMPT,
            tool_names=frozenset(
                {
                    "list_dir",
                    "file_read",
                    "read_document",
                    "search_files",
                    "search_memory",
                    "web_search",
                    "web_fetch",
                    "session_search",
                }
            ),
        )
    if normalized == "plan":
        return ArchetypeSpec(
            name="plan",
            max_steps=PLAN_MAX_STEPS,
            system_prompt=PLAN_SUB_PROMPT,
            tool_names=frozenset(
                {
                    "list_dir",
                    "file_read",
                    "read_document",
                    "search_files",
                    "search_memory",
                    "web_search",
                    "web_fetch",
                    "session_search",
                }
            ),
        )
    return None


def resolve_tools(archetype: str, deps: SubAgentDeps) -> list[Tool]:
    from secretary.agent.tools.code_exec import CodeExecTool
    from secretary.agent.tools.documents import ReadDocumentTool

    spec = get_archetype(archetype, deps.lumina_dir)
    if spec is None:
        return []
    allowed = spec.tool_names
    if allowed is None:
        if spec.name == "explore":
            allowed = frozenset(
                {
                    "list_dir",
                    "file_read",
                    "read_document",
                    "search_files",
                    "search_memory",
                    "web_search",
                    "web_fetch",
                    "session_search",
                }
            )
        elif spec.name == "verify":
            allowed = frozenset(
                {
                    "list_dir",
                    "file_read",
                    "read_document",
                    "search_files",
                    "search_memory",
                    "web_search",
                    "web_fetch",
                    "session_search",
                }
            )
        else:
            return []

    factories: dict[str, Tool] = {
        "list_dir": ListDirTool(),
        "file_read": FileReadTool(),
        "read_document": ReadDocumentTool(),
        "search_files": SearchFilesTool(),
        "search_memory": SearchMemoryTool(deps.memory_store),
        "web_search": WebSearchTool(),
        "web_fetch": WebFetchTool(),
        "session_search": SessionSearchTool(deps.memory),
        "file_write": FileWriteTool(),
        "patch": PatchTool(),
        "shell": ShellTool(),
        "code_exec": CodeExecTool(),
    }
    tools: list[Tool] = []
    for key in sorted(allowed):
        tool = factories.get(key)
        if tool is not None:
            tools.append(tool)
    return tools


def build_messages(
    *,
    goal: str,
    context: str,
    spec: ArchetypeSpec,
    success_criteria: str = "",
) -> list[dict[str, str]]:
    context_block = context.strip() or "None."
    user_content = f"## Task\n{goal.strip()}\n\n## Context\n{context_block}"
    if success_criteria:
        user_content += f"\n\n## 成功标准（机器可验证）\n{success_criteria}"
    return [
        {"role": "system", "content": spec.system_prompt},
        {"role": "user", "content": user_content},
    ]
