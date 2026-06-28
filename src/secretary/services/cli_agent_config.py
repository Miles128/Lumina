"""Persistent CLI agent provider configuration (FR-30)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,47}$")
PromptMode = Literal["argv_tail", "stdin"]


class CliSummaryConfig(BaseModel):
    from_stream: str = Field(default="stdout", alias="from")
    max_chars: int = Field(default=8000, ge=500, le=100_000)

    model_config = {"populate_by_name": True}


class CliProviderConfig(BaseModel):
    command: str
    args: list[str] = Field(default_factory=list)
    prompt_mode: PromptMode = "argv_tail"
    timeout: int = Field(default=600, ge=30, le=3600)
    needs_confirmation: bool = True
    enabled: bool = True
    env: dict[str, str] = Field(default_factory=dict)
    available_check: str = ""
    summary: CliSummaryConfig = Field(default_factory=CliSummaryConfig)


class CliAgentDefaults(BaseModel):
    provider: str = "codex"
    needs_confirmation: bool = True


class CliAgentConfigDocument(BaseModel):
    providers: dict[str, CliProviderConfig] = Field(default_factory=dict)
    defaults: CliAgentDefaults = Field(default_factory=CliAgentDefaults)


def default_providers() -> dict[str, CliProviderConfig]:
    return {
        "codex": CliProviderConfig(
            command="codex",
            args=["exec", "--full-auto"],
            prompt_mode="argv_tail",
            timeout=600,
            available_check="codex",
        ),
        "claude": CliProviderConfig(
            command="claude",
            args=["-p", "--output-format", "text"],
            prompt_mode="argv_tail",
            timeout=300,
            available_check="claude",
        ),
        "opencode": CliProviderConfig(
            command="opencode",
            args=["run"],
            prompt_mode="stdin",
            timeout=600,
            available_check="opencode",
        ),
    }


class CliAgentConfigStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> CliAgentConfigDocument:
        if not self._path.exists():
            return CliAgentConfigDocument(providers=default_providers())
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        document = CliAgentConfigDocument.model_validate(payload)
        merged = dict(default_providers())
        merged.update(document.providers)
        return document.model_copy(update={"providers": merged})

    def load_persisted(self) -> CliAgentConfigDocument:
        if not self._path.exists():
            return CliAgentConfigDocument()
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return CliAgentConfigDocument.model_validate(payload)

    def save(self, document: CliAgentConfigDocument) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            document.model_dump_json(indent=2, by_alias=True),
            encoding="utf-8",
        )

    def get_provider(self, name: str) -> CliProviderConfig | None:
        document = self.load()
        cfg = document.providers.get(name)
        if cfg is None or not cfg.enabled:
            return None
        return cfg

    def list_view(self) -> list[dict[str, object]]:
        document = self.load()
        rows: list[dict[str, object]] = []
        for name in sorted(document.providers):
            cfg = document.providers[name]
            rows.append(
                {
                    "name": name,
                    "enabled": cfg.enabled,
                    "command": cfg.command,
                    "args": cfg.args,
                    "timeout": cfg.timeout,
                    "needs_confirmation": cfg.needs_confirmation,
                    "prompt_mode": cfg.prompt_mode,
                    "available_check": cfg.available_check,
                }
            )
        return rows

    def upsert_provider(self, name: str, config: CliProviderConfig) -> None:
        if not _NAME_RE.match(name):
            raise ValueError(f"无效的 provider 名称: {name}")
        document = self.load_persisted()
        providers = dict(document.providers)
        providers[name] = config
        self.save(document.model_copy(update={"providers": providers}))

    def remove_provider(self, name: str) -> bool:
        document = self.load_persisted()
        if name not in document.providers:
            return False
        providers = dict(document.providers)
        del providers[name]
        self.save(document.model_copy(update={"providers": providers}))
        return True

    def status(self) -> dict[str, Any]:
        return {
            "config_path": str(self._path),
            "providers": self.list_view(),
            "defaults": self.load().defaults.model_dump(),
        }
