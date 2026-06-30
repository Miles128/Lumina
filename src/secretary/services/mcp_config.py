"""Persistent MCP server configuration for Lumina."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

_HERMES_CONFIG = Path.home() / ".hermes" / "config.yaml"
_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,47}$")


class McpServerConfig(BaseModel):
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    transport: str = "stdio"
    timeout: int = Field(default=120, ge=5, le=600)
    enabled: bool = True


class McpConfigDocument(BaseModel):
    servers: dict[str, McpServerConfig] = Field(default_factory=dict)


class McpConfigStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> McpConfigDocument:
        """Load persisted config. Hermes is never auto-merged; use import_from_hermes()."""
        if not self._path.exists():
            return McpConfigDocument()
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return McpConfigDocument.model_validate(payload)

    def save(self, document: McpConfigDocument) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            document.model_dump_json(indent=2, exclude_none=True),
            encoding="utf-8",
        )

    def load_persisted(self) -> McpConfigDocument:
        return self.load()

    def list_view(self) -> list[dict[str, object]]:
        document = self.load()
        rows: list[dict[str, object]] = []
        for name, config in sorted(document.servers.items()):
            rows.append(
                {
                    "name": name,
                    "enabled": config.enabled,
                    "transport": config.transport,
                    "command": config.command,
                    "args": config.args,
                    "url": config.url,
                    "timeout": config.timeout,
                }
            )
        return rows

    def upsert_server(self, name: str, config: McpServerConfig) -> None:
        if not _NAME_RE.match(name):
            raise ValueError(f"无效的服务器名称: {name}")
        document = self.load_persisted()
        servers = dict(document.servers)
        servers[name] = config
        self.save(document.model_copy(update={"servers": servers}))

    def remove_server(self, name: str) -> bool:
        document = self.load()
        if name not in document.servers:
            return False
        servers = dict(document.servers)
        del servers[name]
        self.save(document.model_copy(update={"servers": servers}))
        return True

    def import_from_hermes(self) -> int:
        """Copy Hermes mcp_servers into Lumina config (Lumina entries win)."""
        document = self.load()
        hermes = _load_hermes_servers()
        if not hermes:
            return 0
        servers = dict(document.servers)
        added = 0
        for name, config in hermes.items():
            if name in servers:
                continue
            servers[name] = config
            added += 1
        if added:
            self.save(document.model_copy(update={"servers": servers}))
        return added

    def add_filesystem_server(self, root: Path) -> bool:
        """Register @modelcontextprotocol/server-filesystem if not already present."""
        resolved = root.expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"目录不存在: {resolved}")
        document = self.load_persisted()
        if "filesystem" in document.servers:
            return False
        self.upsert_server(
            "filesystem",
            McpServerConfig(
                command="npx",
                args=[
                    "-y",
                    "@modelcontextprotocol/server-filesystem",
                    str(resolved),
                ],
                enabled=True,
                transport="stdio",
                timeout=120,
            ),
        )
        return True

    def ensure_filesystem_server(self, preferred_root: Path | None = None) -> bool:
        """Add filesystem MCP on first run if missing."""
        if "filesystem" in self.load_persisted().servers:
            return False
        candidates: list[Path] = []
        if preferred_root is not None:
            candidates.append(preferred_root.expanduser())
        candidates.extend([Path.home() / "Documents", Path.home()])
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if not resolved.is_dir():
                continue
            self.upsert_server(
                "filesystem",
                McpServerConfig(
                    command="npx",
                    args=[
                        "-y",
                        "@modelcontextprotocol/server-filesystem",
                        str(resolved),
                    ],
                    enabled=True,
                    transport="stdio",
                    timeout=120,
                ),
            )
            return True
        return False


def _load_hermes_servers() -> dict[str, McpServerConfig]:
    if not _HERMES_CONFIG.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    try:
        raw = yaml.safe_load(_HERMES_CONFIG.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    servers = raw.get("mcp_servers")
    if not isinstance(servers, dict):
        return {}
    parsed: dict[str, McpServerConfig] = {}
    for name, item in servers.items():
        if not _NAME_RE.match(str(name)) or not isinstance(item, dict):
            continue
        command = str(item.get("command") or "")
        url = str(item.get("url") or "")
        if not command and not url:
            continue
        raw_env = item.get("env")
        raw_args = item.get("args")
        env: dict[str, str] = {str(k): str(v) for k, v in raw_env.items()} if isinstance(raw_env, dict) else {}
        args: list[str] = [str(arg) for arg in raw_args] if isinstance(raw_args, list) else []
        parsed[str(name)] = McpServerConfig(
            command=command,
            args=args,
            env=env,
            url=url,
            transport=str(item.get("transport") or ("stdio" if command else "http")),
            timeout=int(item.get("timeout") or 120),
            enabled=True,
        )
    return parsed
