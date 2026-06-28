"""Persistent CLI agent provider configuration (FR-30)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
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
    prompt_flag: str = ""
    timeout: int = Field(default=600, ge=30, le=3600)
    needs_confirmation: bool = True
    enabled: bool = False
    env: dict[str, str] = Field(default_factory=dict)
    available_check: str = ""
    summary: CliSummaryConfig = Field(default_factory=CliSummaryConfig)


class CliAgentDefaults(BaseModel):
    enabled: bool = False
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
            enabled=False,
        ),
        "kimi": CliProviderConfig(
            command="kimi",
            args=["-p", "--output-format", "text", "-y"],
            prompt_mode="argv_tail",
            prompt_flag="-p",
            timeout=600,
            available_check="kimi",
            enabled=False,
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

    def is_enabled(self) -> bool:
        return self.load().defaults.enabled

    def get_provider(self, name: str) -> CliProviderConfig | None:
        document = self.load()
        if not document.defaults.enabled:
            return None
        cfg = document.providers.get(name)
        if cfg is None or not cfg.enabled:
            return None
        return cfg

    def resolve_provider(self, name: str) -> CliProviderConfig | None:
        """Return provider config even when globally disabled (for settings UI)."""
        return self.load().providers.get(name)

    @staticmethod
    def provider_installed(cfg: CliProviderConfig) -> bool:
        check = (cfg.available_check or cfg.command).strip()
        return bool(check and shutil.which(check))

    def list_view(self) -> list[dict[str, object]]:
        document = self.load()
        rows: list[dict[str, object]] = []
        for name in sorted(document.providers):
            cfg = document.providers[name]
            rows.append(self._provider_row(name, cfg))
        return rows

    @classmethod
    def _provider_row(cls, name: str, cfg: CliProviderConfig) -> dict[str, object]:
        return {
            "name": name,
            "enabled": cfg.enabled,
            "command": cfg.command,
            "args": cfg.args,
            "timeout": cfg.timeout,
            "needs_confirmation": cfg.needs_confirmation,
            "prompt_mode": cfg.prompt_mode,
            "prompt_flag": cfg.prompt_flag,
            "available_check": cfg.available_check,
            "installed": cls.provider_installed(cfg),
        }

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

    def update_defaults(
        self,
        *,
        enabled: bool | None = None,
        provider: str | None = None,
        needs_confirmation: bool | None = None,
    ) -> CliAgentDefaults:
        document = self.load_persisted()
        patch: dict[str, Any] = {}
        if enabled is not None:
            patch["enabled"] = enabled
        if provider is not None:
            if provider not in self.load().providers:
                raise ValueError(f"未知 provider: {provider}")
            patch["provider"] = provider
        if needs_confirmation is not None:
            patch["needs_confirmation"] = needs_confirmation
        defaults = document.defaults.model_copy(update=patch)
        self.save(document.model_copy(update={"defaults": defaults}))
        return defaults

    def set_provider_enabled(self, name: str, enabled: bool) -> CliProviderConfig:
        document = self.load()
        if name not in document.providers:
            raise ValueError(f"未知 provider: {name}")
        persisted = self.load_persisted()
        providers = dict(persisted.providers)
        base = document.providers[name]
        if name in providers:
            cfg = providers[name].model_copy(update={"enabled": enabled})
        else:
            cfg = base.model_copy(update={"enabled": enabled})
        providers[name] = cfg
        self.save(persisted.model_copy(update={"providers": providers}))
        return cfg

    def test_provider(self, name: str) -> dict[str, object]:
        document = self.load()
        cfg = document.providers.get(name)
        if cfg is None:
            return {"ok": False, "message": f"未知 provider: {name}"}
        check = (cfg.available_check or cfg.command).strip()
        path = shutil.which(check)
        if not path:
            return {"ok": False, "message": f"未找到 CLI：{check}（请安装并加入 PATH）"}
        version_args = {
            "codex": ["--version"],
            "kimi": ["-V"],
        }.get(name, ["--version"])
        try:
            completed = subprocess.run(
                [cfg.command, *version_args],
                capture_output=True,
                text=True,
                timeout=15,
            )
            detail = (completed.stdout or completed.stderr or "").strip().splitlines()
            snippet = detail[0][:120] if detail else f"exit {completed.returncode}"
            ok = completed.returncode == 0
            return {
                "ok": ok,
                "message": snippet if ok else f"CLI 返回非零退出码：{snippet}",
                "path": path,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "检测超时", "path": path}
        except OSError as exc:
            return {"ok": False, "message": str(exc), "path": path}

    def status(self) -> dict[str, Any]:
        document = self.load()
        enabled_providers = [
            row["name"]
            for row in self.list_view()
            if row["enabled"] and row["installed"]
        ]
        return {
            "config_path": str(self._path),
            "enabled": document.defaults.enabled,
            "active": document.defaults.enabled and bool(enabled_providers),
            "providers": self.list_view(),
            "defaults": document.defaults.model_dump(),
            "enabled_providers": enabled_providers,
        }
