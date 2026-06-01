"""Persistent agent / LLM configuration (Hermes-compatible)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from secretary.agent.llm_config import (
    LlmConfig,
    is_placeholder_api_key,
    load_hermes_llm_config,
    normalize_base_url,
    normalize_model_name,
)
from secretary.config import Settings
from secretary.exceptions import AgentError, SecretaryError

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
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


class AgentConfigDocument(BaseModel):
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_history_turns: int = Field(default=16, ge=2, le=64)
    use_hermes_fallback: bool = True
    response_style: str = Field(default="standard", pattern="^(standard|brief)$")
    shell_working_dir: str = ""


@dataclass(frozen=True)
class AgentConfigView:
    provider: str
    api_key: str
    api_key_masked: str
    base_url: str
    model: str
    temperature: float
    max_history_turns: int
    use_hermes_fallback: bool
    response_style: str
    shell_working_dir: str
    status: str
    status_message: str
    active_source: str


class AgentConfigStore:
    def __init__(self, config_path: Path) -> None:
        self._path = config_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AgentConfigDocument:
        if not self._path.exists():
            return AgentConfigDocument()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SecretaryError(f"invalid agent config: {self._path}") from exc
        return AgentConfigDocument.model_validate(raw)

    def save(self, document: AgentConfigDocument) -> None:
        self._path.write_text(
            document.model_dump_json(indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

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
            use_hermes_fallback=current.use_hermes_fallback,
            response_style=current.response_style,
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
            message = "请填写 API Key 并测试连接，或开启 Hermes 配置回退"
        else:
            status = "ready"
            source_label = {
                "local": "灵犀本地配置",
                "env": ".env 环境变量",
                "hermes": "Hermes（.env / config）",
            }.get(resolved.source, resolved.source)
            hint = ""
            if resolved.source == "hermes":
                hint = " · 已从 ~/.hermes/.env 读取真实 Key"
            message = f"当前使用 {source_label} · 模型 {resolved.model}{hint}"
        return AgentConfigView(
            provider=document.provider,
            api_key=document.api_key,
            api_key_masked=_mask_key(document.api_key),
            base_url=document.base_url,
            model=document.model,
            temperature=document.temperature,
            max_history_turns=document.max_history_turns,
            use_hermes_fallback=document.use_hermes_fallback,
            response_style=document.response_style,
            shell_working_dir=document.shell_working_dir,
            status=status,
            status_message=message,
            active_source=resolved.source if resolved else "none",
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
            model=normalize_model_name(document.model.strip() or "deepseek-chat"),
            source="local",
        )
    if settings.llm_api_key.strip() and not is_placeholder_api_key(settings.llm_api_key):
        return LlmConfig(
            api_key=settings.llm_api_key.strip(),
            base_url=_normalize_base_url(settings.llm_base_url),
            model=normalize_model_name(settings.llm_model.strip() or "deepseek-chat"),
            source="env",
        )
    if document.use_hermes_fallback:
        hermes = load_hermes_llm_config()
        if hermes:
            return LlmConfig(
                api_key=hermes.api_key,
                base_url=hermes.base_url,
                model=normalize_model_name(hermes.model),
                source="hermes",
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
