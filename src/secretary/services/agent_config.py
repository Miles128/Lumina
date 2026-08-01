"""Persistent agent / LLM configuration for Lumina."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from secretary.agent.harness_config import HarnessConfig
from secretary.agent.llm_config import (
    DEFAULT_MODEL,
    LlmConfig,
    is_placeholder_api_key,
    load_hermes_llm_config,
    normalize_base_url,
    normalize_model_name,
)
from secretary.config import Settings
from secretary.exceptions import AgentError
from secretary.services.base_config_store import BaseJsonConfigStore

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "anthropic/claude-sonnet-4",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "custom": {
        "label": "自定义",
        "base_url": "",
        "model": "",
    },
}

# Curated model + base_url pairs for the settings UI dropdown.
MODEL_PRESETS: list[dict[str, str]] = [
    {
        "id": "deepseek-v4-flash",
        "label": "DeepSeek V4 Flash",
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
    },
    {
        "id": "deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
    },
    {
        "id": "openai-gpt-4o-mini",
        "label": "OpenAI GPT-4o mini",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    {
        "id": "openai-gpt-4o",
        "label": "OpenAI GPT-4o",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    },
    {
        "id": "openai-gpt-4.1",
        "label": "OpenAI GPT-4.1",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1",
    },
    {
        "id": "openai-gpt-4.1-mini",
        "label": "OpenAI GPT-4.1 mini",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
    },
    {
        "id": "openrouter-claude-sonnet",
        "label": "Claude Sonnet 4 (OpenRouter)",
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "anthropic/claude-sonnet-4",
    },
    {
        "id": "openrouter-claude-opus",
        "label": "Claude Opus 4 (OpenRouter)",
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "anthropic/claude-opus-4",
    },
    {
        "id": "openrouter-gemini-flash",
        "label": "Gemini 2.5 Flash (OpenRouter)",
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "google/gemini-2.5-flash",
    },
    {
        "id": "openrouter-gemini-pro",
        "label": "Gemini 2.5 Pro (OpenRouter)",
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "google/gemini-2.5-pro",
    },
    {
        "id": "openrouter-deepseek-flash",
        "label": "DeepSeek V4 Flash (OpenRouter)",
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "deepseek/deepseek-v4-flash",
    },
]


class BackgroundConfig(BaseModel):
    """Periodic background think + daily MEMORY.md summarization."""

    think_enabled: bool = True
    think_interval_hours: int = Field(default=6, ge=1, le=168)
    memory_summary_enabled: bool = True
    memory_summary_hour: int = Field(default=23, ge=0, le=23)


class AgentConfigDocument(BaseModel):
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = DEFAULT_MODEL
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_history_turns: int = Field(default=16, ge=2, le=64)
    response_style: str = Field(default="standard", pattern="^(standard|brief)$")
    agent_profile: str = Field(default="auto", pattern="^(auto|build|ask|plan)$")
    shell_working_dir: str = ""
    hooks: dict[str, Any] = Field(default_factory=dict)
    harness: HarnessConfig = Field(default_factory=HarnessConfig)
    background: BackgroundConfig = Field(default_factory=BackgroundConfig)


@dataclass(frozen=True)
class AgentConfigView:
    provider: str
    api_key: str
    api_key_masked: str
    base_url: str
    model: str
    temperature: float
    max_history_turns: int
    response_style: str
    agent_profile: str
    shell_working_dir: str
    status: str
    status_message: str
    active_source: str
    harness: HarnessConfig


class AgentConfigStore(BaseJsonConfigStore[AgentConfigDocument]):
    def __init__(self, config_path: Path) -> None:
        super().__init__(config_path)

    def load(self) -> AgentConfigDocument:
        raw = self._read_json_or_none()
        if raw is None:
            return AgentConfigDocument()
        return AgentConfigDocument.model_validate(raw)

    def save(self, document: AgentConfigDocument) -> None:
        self._write_json(document)

    def update(self, payload: dict[str, object]) -> AgentConfigDocument:
        current = self.load()
        merged = current.model_dump()
        for key, value in payload.items():
            if key not in merged:
                continue
            if key == "api_key" and (
                value == ""
                or value == "********"
                or is_placeholder_api_key(str(value))
            ):
                continue
            if key == "harness" and isinstance(value, dict):
                harness_merged = dict(merged.get("harness") or {})
                harness_merged.update(value)
                merged["harness"] = harness_merged
                continue
            if key == "background" and isinstance(value, dict):
                background_merged = dict(merged.get("background") or {})
                background_merged.update(value)
                merged["background"] = background_merged
                continue
            merged[key] = value
        if payload.get("provider") and payload["provider"] != current.provider:
            preset = PROVIDER_PRESETS.get(str(payload["provider"]))
            if preset and str(payload["provider"]) != "custom":
                if not payload.get("base_url"):
                    merged["base_url"] = preset["base_url"]
                if not payload.get("model"):
                    merged["model"] = preset["model"]
        document = AgentConfigDocument.model_validate(merged)
        self.save(document)
        return document

    def import_from_hermes(self) -> AgentConfigDocument:
        hermes = load_hermes_llm_config()
        if hermes is None:
            raise AgentError("未找到可用的 Hermes 配置（~/.hermes/config.yaml）")
        current = self.load()
        provider = "deepseek"
        if "openrouter" in hermes.base_url:
            provider = "openrouter"
        elif "openai.com" in hermes.base_url:
            provider = "openai"
        elif hermes.base_url:
            provider = "custom"
        document = AgentConfigDocument(
            provider=provider,
            api_key=hermes.api_key,
            base_url=hermes.base_url,
            model=normalize_model_name(hermes.model),
            temperature=current.temperature,
            max_history_turns=current.max_history_turns,
            response_style=current.response_style,
            harness=current.harness,
            background=current.background,
            hooks=current.hooks,
            agent_profile=current.agent_profile,
            shell_working_dir=current.shell_working_dir,
        )
        self.save(document)
        return document

    def apply_to_settings(self, settings: Settings) -> None:
        document = self.load()
        if document.api_key.strip():
            settings.llm_api_key = document.api_key.strip()
            settings.llm_base_url = document.base_url.strip()
            settings.llm_model = document.model.strip()

    def get_view(self, settings: Settings) -> AgentConfigView:
        document = self.load()
        resolved = resolve_effective_llm_config(settings, self)
        if resolved is None:
            status = "not_configured"
            message = "请填写 API Key 并测试连接，或点击『从 Hermes 导入』"
        else:
            status = "ready"
            source_label = {
                "local": "灵犀本地配置",
                "env": ".env 环境变量",
            }.get(resolved.source, resolved.source)
            message = f"当前使用 {source_label} · 模型 {resolved.model}"
        return AgentConfigView(
            provider=document.provider,
            api_key=document.api_key,
            api_key_masked=_mask_key(document.api_key),
            base_url=document.base_url,
            model=document.model,
            temperature=document.temperature,
            max_history_turns=document.max_history_turns,
            response_style=document.response_style,
            agent_profile=document.agent_profile,
            shell_working_dir=document.shell_working_dir,
            status=status,
            status_message=message,
            active_source=resolved.source if resolved else "none",
            harness=document.harness,
        )


def resolve_background_config(
    settings: Settings,
    store: AgentConfigStore,
) -> BackgroundConfig:
    """Effective background flags.

    If agent.json already has a ``background`` key (user saved in UI), that wins.
    Otherwise fall back to Settings / env (defaults now True).
    """
    raw = store._read_json_or_none()
    if isinstance(raw, dict) and "background" in raw:
        return store.load().background
    return BackgroundConfig(
        think_enabled=settings.think_enabled,
        think_interval_hours=settings.think_interval_hours,
        memory_summary_enabled=settings.memory_summary_enabled,
        memory_summary_hour=settings.memory_summary_hour,
    )


def resolve_effective_llm_config(
    settings: Settings,
    store: AgentConfigStore,
) -> LlmConfig | None:
    document = store.load()
    if document.api_key.strip() and not is_placeholder_api_key(document.api_key):
        return LlmConfig(
            api_key=document.api_key.strip(),
            base_url=_normalize_base_url(document.base_url),
            model=normalize_model_name(document.model.strip() or DEFAULT_MODEL),
            source="local",
        )
    if settings.llm_api_key.strip() and not is_placeholder_api_key(settings.llm_api_key):
        return LlmConfig(
            api_key=settings.llm_api_key.strip(),
            base_url=_normalize_base_url(settings.llm_base_url),
            model=normalize_model_name(settings.llm_model.strip() or DEFAULT_MODEL),
            source="env",
        )
    return None


def _normalize_base_url(base_url: str) -> str:
    return normalize_base_url(base_url)


def _mask_key(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    if len(cleaned) <= 8:
        return "********"
    return f"{cleaned[:4]}...{cleaned[-4:]}"
