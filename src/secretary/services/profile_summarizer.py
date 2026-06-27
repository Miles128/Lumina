"""LLM-assisted profile summarization with rule-based fallback."""

from __future__ import annotations

from datetime import UTC, datetime

from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig
from secretary.core.types import ProfileSection, UserProfile
from secretary.exceptions import AgentError
from secretary.memory.db import MemoryStore
from secretary.memory.profile import ProfileBuilder
from secretary.services.local_documents_profiler import LocalDocumentsProfile


def build_profile(
    store: MemoryStore,
    local_profile: LocalDocumentsProfile | None,
    llm_config: LlmConfig | None,
) -> UserProfile:
    rule_profile = ProfileBuilder(store, local_profile).build()
    if llm_config is None:
        return rule_profile
    if not any(section.evidence_count > 0 for section in rule_profile.sections):
        return rule_profile
    try:
        return _summarize_with_llm(rule_profile, llm_config)
    except AgentError:
        return rule_profile


def _summarize_with_llm(rule_profile: UserProfile, llm_config: LlmConfig) -> UserProfile:
    evidence_lines: list[str] = []
    for section in rule_profile.sections:
        if section.evidence_count == 0:
            continue
        evidence_lines.append(f"## {section.title}\n{section.content}")

    prompt = (
        "根据以下从用户数据源同步的原始记录，写中文个人画像摘要。"
        "保留章节标题（工作节奏、阅读偏好、内容兴趣、信息习惯、本地文档摘录），"
        "每节 2-5 句，只归纳已有事实，禁止编造。\n\n"
        + "\n\n".join(evidence_lines)
    )
    body = chat_completion(
        llm_config,
        [
            {"role": "system", "content": "你是个人画像摘要助手。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )

    sections: list[ProfileSection] = []
    for section in rule_profile.sections:
        extracted = _extract_section(body, section.title)
        content = extracted if extracted else section.content
        sections.append(
            ProfileSection(
                key=section.key,
                title=section.title,
                content=content,
                evidence_count=section.evidence_count,
            )
        )

    overview = "以下为基于同步数据生成的语义摘要，不含推测。"
    markdown = _render_markdown(overview, sections)
    return UserProfile(
        generated_at=datetime.now(UTC),
        sections=sections,
        markdown=markdown,
    )


def _extract_section(markdown: str, title: str) -> str:
    marker = f"## {title}"
    start = markdown.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    rest = markdown[start:].lstrip("\n")
    end = rest.find("\n## ")
    block = rest[:end] if end >= 0 else rest
    return block.strip()


def _render_markdown(overview: str, sections: list[ProfileSection]) -> str:
    lines = [
        "# USER 画像",
        "",
        f"> 自动生成时间：{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## 说明",
        overview,
        "",
    ]
    for section in sections:
        lines.extend([f"## {section.title}", section.content, ""])
    return "\n".join(lines).strip() + "\n"
