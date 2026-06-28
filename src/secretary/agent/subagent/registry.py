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
    "Use list_dir, file_read, search_files, search_memory, web_search, "
    "web_fetch, and session_search as needed.\n"
    "Do not modify files or spawn other agents.\n"
    "Report findings as concise bullet points; include file paths when relevant.\n"
    "Do not output internal reasoning chains or step-by-step meta commentary."
)

WORKER_PROMPT = (
    "You are a worker sub-agent for Lumina.\n"
    "You may read and modify the workspace using file_write, patch, and shell.\n"
    "Destructive or risky operations may pause for user confirmation.\n"
    "Do not spawn other agents. Return a concise summary of what you changed or found."
)

VERIFY_PROMPT = (
    "You are a verification sub-agent for Lumina (read-only).\n"
    "Review the task using list_dir, file_read, search_files, and search_memory.\n"
    "Output: (1) Pass/Fail, (2) issues found, (3) suggested fixes.\n"
    "Do not modify files or spawn other agents."
)

PLAN_SUB_PROMPT = (
    "You are a planning sub-agent for Lumina (read-only).\n"
    "Survey the workspace with list_dir, file_read, search_files, and search_memory.\n"
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
                    "search_files",
                    "search_memory",
                    "web_search",
                    "web_fetch",
                    "session_search",
                    "file_write",
                    "patch",
                    "shell",
                }
            ),
        )
    if normalized == "verify":
        return ArchetypeSpec(name="verify", max_steps=VERIFY_MAX_STEPS, system_prompt=VERIFY_PROMPT)
    if normalized == "plan":
        return ArchetypeSpec(
            name="plan",
            max_steps=PLAN_MAX_STEPS,
            system_prompt=PLAN_SUB_PROMPT,
            tool_names=frozenset(
                {
                    "list_dir",
                    "file_read",
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
        "search_files": SearchFilesTool(),
        "search_memory": SearchMemoryTool(deps.memory_store),
        "web_search": WebSearchTool(),
        "web_fetch": WebFetchTool(),
        "session_search": SessionSearchTool(deps.hermes),
        "file_write": FileWriteTool(),
        "patch": PatchTool(),
        "shell": ShellTool(),
    }
    tools: list[Tool] = []
    for key in sorted(allowed):
        tool = factories.get(key)
        if tool is not None:
            tools.append(tool)
    return tools


def build_messages(*, goal: str, context: str, spec: ArchetypeSpec) -> list[dict[str, str]]:
    context_block = context.strip() or "None."
    user_content = f"## Task\n{goal.strip()}\n\n## Context\n{context_block}"
    return [
        {"role": "system", "content": spec.system_prompt},
        {"role": "user", "content": user_content},
    ]
