"""Archetype definitions: tool sets and sub-agent system prompts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from secretary.agent.loop import (
    FileReadTool,
    ListDirTool,
    SearchMemoryTool,
    SessionSearchTool,
    Tool,
    WebFetchTool,
)
from secretary.agent.p0_tools import SearchFilesTool
from secretary.agent.subagent.policy import EXPLORE_MAX_STEPS, PHASE1_ARCHETYPES
from secretary.agent.web_search import WebSearchTool

if TYPE_CHECKING:
    from secretary.agent.subagent.runner import SubAgentDeps


@dataclass(frozen=True)
class ArchetypeSpec:
    name: str
    max_steps: int
    system_prompt: str


EXPLORE_PROMPT = (
    "You are a read-only research sub-agent for Lumina.\n"
    "Use list_dir, file_read, search_files, search_memory, web_search, "
    "web_fetch, and session_search as needed.\n"
    "Do not modify files or spawn other agents.\n"
    "Report findings as concise bullet points; include file paths when relevant.\n"
    "Do not output internal reasoning chains or step-by-step meta commentary."
)


def get_archetype(name: str) -> ArchetypeSpec | None:
    normalized = name.strip().lower()
    if normalized not in PHASE1_ARCHETYPES:
        return None
    if normalized == "explore":
        return ArchetypeSpec(name="explore", max_steps=EXPLORE_MAX_STEPS, system_prompt=EXPLORE_PROMPT)
    return None


def resolve_tools(archetype: str, deps: SubAgentDeps) -> list[Tool]:
    spec = get_archetype(archetype)
    if spec is None:
        return []
    if spec.name == "explore":
        return [
            ListDirTool(),
            FileReadTool(),
            SearchFilesTool(),
            SearchMemoryTool(deps.memory_store),
            WebSearchTool(),
            WebFetchTool(),
            SessionSearchTool(deps.hermes),
        ]
    return []


def build_messages(*, goal: str, context: str, spec: ArchetypeSpec) -> list[dict[str, str]]:
    context_block = context.strip() or "None."
    user_content = f"## Task\n{goal.strip()}\n\n## Context\n{context_block}"
    return [
        {"role": "system", "content": spec.system_prompt},
        {"role": "user", "content": user_content},
    ]
