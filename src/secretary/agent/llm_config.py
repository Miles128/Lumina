"""Resolve LLM credentials from local config, env, or Hermes."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from secretary.config import Settings

_HERMES_CONFIG = Path.home() / ".hermes" / "config.yaml"
_HERMES_ENV = Path.home() / ".hermes" / ".env"

MODEL_ALIASES: dict[str, str] = {
    "deepseek-v4-flash": "deepseek-chat",
    "deepseek-v4": "deepseek-chat",
    "deepseek-v3": "deepseek-chat",
    "deepseek-v3.2": "deepseek-chat",
}

_PROVIDER_ENV_KEYS: dict[str, tuple[str, ...]] = {
    "deepseek": ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
}


@dataclass(frozen=True)
class LlmConfig:
    api_key: str
    base_url: str
    model: str
    source: str


def normalize_model_name(model: str) -> str:
    cleaned = model.strip()
    if not cleaned:
        return "deepseek-chat"
    return MODEL_ALIASES.get(cleaned, cleaned)


def is_placeholder_api_key(api_key: str) -> bool:
    cleaned = api_key.strip()
    if not cleaned:
        return True
    if cleaned in {"********", "sk-...", "your-api-key"}:
        return True
    if "..." in cleaned:
        return True
    if cleaned.startswith("sk-") and len(cleaned) < 20:
        return True
    return False


def resolve_llm_config(
    settings: Settings, agent_config_store: object | None = None
) -> LlmConfig | None:
    from secretary.services.agent_config import AgentConfigStore, resolve_effective_llm_config

    store: AgentConfigStore = (
        agent_config_store  # type: ignore[assignment]
        if agent_config_store is not None
        else AgentConfigStore(settings.resolved_data_dir() / "agent.json")
    )
    return resolve_effective_llm_config(settings, store)


def load_hermes_llm_config() -> LlmConfig | None:
    provider = "deepseek"
    base_url = "https://api.deepseek.com"
    model = "deepseek-chat"
    api_key = ""

    if _HERMES_CONFIG.exists():
        text = _HERMES_CONFIG.read_text(encoding="utf-8")
        provider = _yaml_scalar(text, "provider") or provider
        base_url = _yaml_scalar(text, "base_url") or base_url
        model = _yaml_scalar(text, "default") or model
        yaml_key = _yaml_scalar(text, "api_key")
        if yaml_key and not is_placeholder_api_key(yaml_key):
            api_key = yaml_key

    if not api_key:
        api_key = _load_hermes_env_key(provider)

    if not api_key or is_placeholder_api_key(api_key):
        return None

    env_base = _load_hermes_env_value("DEEPSEEK_BASE_URL")
    if env_base:
        base_url = env_base

    return LlmConfig(
        api_key=api_key.strip(),
        base_url=normalize_base_url(base_url),
        model=normalize_model_name(model),
        source="hermes",
    )


def _load_hermes_env_key(provider: str) -> str:
    env_values = _read_env_file(_HERMES_ENV)
    for key in _PROVIDER_ENV_KEYS.get(provider, ()):
        value = env_values.get(key, "").strip()
        if value and not is_placeholder_api_key(value):
            return value
    for key in ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        value = env_values.get(key, "").strip()
        if value and not is_placeholder_api_key(value):
            return value
    for key in ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        value = os.environ.get(key, "").strip()
        if value and not is_placeholder_api_key(value):
            return value
    return ""


def _load_hermes_env_value(name: str) -> str:
    env_values = _read_env_file(_HERMES_ENV)
    return env_values.get(name, os.environ.get(name, "")).strip()


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def normalize_base_url(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    if not cleaned:
        return "https://api.deepseek.com/v1"
    if cleaned.endswith("/v1"):
        return cleaned
    if "openrouter.ai" in cleaned and not cleaned.endswith("/v1"):
        return f"{cleaned}/v1"
    if cleaned in {"https://api.deepseek.com", "https://api.openai.com"}:
        return f"{cleaned}/v1"
    return cleaned


def _yaml_scalar(text: str, key: str) -> str:
    pattern = rf"^\s{{2}}{re.escape(key)}:\s*(.+?)\s*$"
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        return ""
    value = match.group(1).strip().strip("'\"")
    if value.startswith("${") and value.endswith("}"):
        return ""
    return value
