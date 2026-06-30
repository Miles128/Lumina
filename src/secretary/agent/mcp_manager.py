"""MCP client manager: discover external MCP tools and expose them to AgentLoop."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import CancelledError, Future
from concurrent.futures import TimeoutError as FuturesTimeoutError
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from secretary.agent.tools.base import Tool
from secretary.services.mcp_config import McpConfigStore, McpServerConfig

logger = logging.getLogger(__name__)

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import Tool as McpToolDef

    _MCP_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    ClientSession = None  # type: ignore[assignment,misc]
    StdioServerParameters = None  # type: ignore[assignment,misc]
    stdio_client = None  # type: ignore[assignment]
    McpToolDef = Any  # type: ignore[assignment,misc]
    _MCP_AVAILABLE = False

_NAME_SAFE = re.compile(r"[^a-zA-Z0-9_]+")


@dataclass(frozen=True)
class _RegisteredMcpTool:
    server_name: str
    remote_name: str
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    timeout: int


class McpBridgeTool(Tool):
    def __init__(self, manager: McpManager, spec: _RegisteredMcpTool) -> None:
        self._manager = manager
        self._spec = spec
        self.name = f"mcp_{spec.server_name}_{spec.tool_name}"
        self.description = f"[MCP:{spec.server_name}] {spec.description or spec.tool_name}"
        self.needs_confirmation = _needs_confirmation(spec.tool_name)
        self.risk_level = "medium" if self.needs_confirmation else "low"

    def _parameters(self) -> dict[str, Any]:
        schema = dict(self._spec.input_schema or {})
        if schema.get("type") != "object":
            return {"type": "object", "properties": {}, "required": []}
        return schema

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return self._manager.call_tool(
            self._spec.server_name,
            self._spec.remote_name,
            arguments,
            timeout=self._spec.timeout,
        )

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        preview = json.dumps(arguments, ensure_ascii=False)[:240]
        return f"MCP {self._spec.server_name}/{self._spec.tool_name}: {preview}"


@dataclass
class _ServerRuntime:
    name: str
    session: Any
    tools: list[_RegisteredMcpTool]
    stack: Any = None


class McpManager:
    def __init__(self, config_store: McpConfigStore) -> None:
        self._config_store = config_store
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="lumina-mcp", daemon=True)
        self._thread.start()
        self._lock = threading.Lock()
        self._bridge_tools: list[McpBridgeTool] = []
        self._runtimes: dict[str, _ServerRuntime] = {}
        self._loaded = False
        self._loading = False
        self._last_error = ""
        self._connection_fingerprint_cached: str | None = None

    @property
    def available(self) -> bool:
        return _MCP_AVAILABLE

    @property
    def last_error(self) -> str:
        return self._last_error

    def status(self) -> dict[str, object]:
        document = self._config_store.load()
        return {
            "available": self.available,
            "loaded": self._loaded,
            "tool_count": len(self._bridge_tools),
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "server": tool._spec.server_name,
                }
                for tool in self._bridge_tools
            ],
            "servers": [
                {
                    "name": name,
                    "enabled": cfg.enabled,
                    "connected": name in self._runtimes,
                    "transport": cfg.transport,
                }
                for name, cfg in document.servers.items()
            ],
            "config_path": str(self._config_store.path),
            "last_error": self._last_error,
        }

    def get_tools(self) -> list[Tool]:
        try:
            self.ensure_loaded()
        except Exception as exc:
            logger.warning("MCP get_tools degraded: %s", exc)
            self._record_error(f"get_tools: {exc}")
        return list(self._bridge_tools)

    def reload(self, *, force: bool = True) -> None:
        with self._lock:
            if self._loading:
                return
            if not force and self._loaded and not self._config_changed():
                return
            self._loading = True
        try:
            self._run(self._async_reload)
        except Exception as exc:
            logger.warning("MCP reload failed: %s", exc)
            self._record_error(f"reload: {exc}")
        finally:
            with self._lock:
                self._loading = False
                self._loaded = True
                if self._connection_fingerprint_cached is None:
                    self._mark_connected()

    def ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded and not self._config_changed():
                return
            if self._loading:
                return
            self._loading = True
        try:
            self._run(self._async_reload)
        except Exception as exc:
            logger.warning("MCP ensure_loaded failed: %s", exc)
            self._record_error(f"load: {exc}")
        finally:
            with self._lock:
                self._loading = False
                self._loaded = True
                if self._connection_fingerprint_cached is None:
                    self._mark_connected()

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: int,
    ) -> str:
        return self._run(  # type: ignore[no-any-return]
            lambda: self._async_call_tool(server_name, tool_name, arguments),
            timeout=timeout + 5,
        )

    def shutdown(self) -> None:
        try:
            self._run(self._async_shutdown, timeout=10)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _record_error(self, message: str) -> None:
        if self._last_error:
            self._last_error += f"; {message}"
        else:
            self._last_error = message

    def _run(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, Any]],
        *,
        timeout: float = 180,
    ) -> Any:
        coro = coro_factory()
        future: Future[Any] = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except CancelledError as exc:
            logger.warning("MCP task cancelled: %s", exc)
            raise RuntimeError("MCP 连接任务被取消") from exc
        except FuturesTimeoutError as exc:
            logger.warning("MCP task timed out after %.0fs", timeout)
            raise RuntimeError(f"MCP 连接超时（{int(timeout)}s）") from exc

    def _connection_fingerprint(self) -> str:
        document = self._config_store.load()
        parts: list[str] = []
        for name in sorted(document.servers):
            cfg = document.servers[name]
            if not cfg.enabled or not cfg.command:
                continue
            parts.append(
                "|".join(
                    [
                        name,
                        cfg.command,
                        " ".join(cfg.args),
                        str(cfg.timeout),
                        json.dumps(cfg.env, sort_keys=True, ensure_ascii=True),
                    ]
                )
            )
        return "\n".join(parts)

    def _config_changed(self) -> bool:
        return self._connection_fingerprint() != self._connection_fingerprint_cached

    def _mark_connected(self) -> None:
        self._connection_fingerprint_cached = self._connection_fingerprint()

    async def _async_reload(self) -> None:
        try:
            await self._async_shutdown()
        except Exception as exc:
            logger.warning("MCP shutdown during reload: %s", exc)
            self._record_error(f"shutdown: {exc}")
        self._bridge_tools = []
        self._runtimes.clear()
        self._last_error = ""
        if not _MCP_AVAILABLE:
            self._last_error = "未安装 mcp 包"
            self._mark_connected()
            return
        document = self._config_store.load()
        for name, config in document.servers.items():
            if not config.enabled:
                continue
            if config.command:
                try:
                    await self._connect_stdio(name, config)
                except Exception as exc:
                    logger.warning("MCP server %s failed: %s", name, exc)
                    if self._last_error:
                        self._last_error += f"; {name}: {exc}"
                    else:
                        self._last_error = f"{name}: {exc}"
                continue
            if self._last_error:
                self._last_error += f"; {name}: 暂不支持 URL 传输"
            else:
                self._last_error = f"{name}: 暂不支持 URL 传输"
        self._mark_connected()

    async def _connect_stdio(self, name: str, config: McpServerConfig) -> None:
        assert StdioServerParameters is not None
        assert stdio_client is not None
        assert ClientSession is not None
        env = os.environ.copy()
        env.update(config.env)
        params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=env,
        )
        stack = AsyncExitStack()
        try:
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            listed = await session.list_tools()
            specs: list[_RegisteredMcpTool] = []
            for item in listed.tools:
                safe_tool = _safe_name(item.name)
                specs.append(
                    _RegisteredMcpTool(
                        server_name=_safe_name(name),
                        remote_name=str(item.name),
                        tool_name=safe_tool,
                        description=str(item.description or item.name),
                        input_schema=dict(item.inputSchema or {}),
                        timeout=config.timeout,
                    )
                )
            runtime = _ServerRuntime(
                name=name,
                session=session,
                tools=specs,
                stack=stack,
            )
            self._runtimes[name] = runtime
            for spec in specs:
                self._bridge_tools.append(McpBridgeTool(self, spec))
        except Exception:
            await self._close_stack(stack)
            raise

    async def _async_call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        runtime = self._runtimes.get(server_name)
        if runtime is None:
            return f"Error: MCP server '{server_name}' 未连接"
        result = await runtime.session.call_tool(tool_name, arguments)
        chunks: list[str] = []
        for block in result.content:
            text = getattr(block, "text", None)
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
        if chunks:
            return "\n".join(chunks)
        if result.isError:
            return "Error: MCP tool returned an error"
        return "(empty MCP result)"

    async def _close_stack(self, stack: AsyncExitStack | None) -> None:
        if stack is None:
            return
        try:
            await stack.aclose()
        except Exception as exc:
            logger.warning("MCP stack close failed: %s", exc)

    async def _async_shutdown(self) -> None:
        for name, runtime in list(self._runtimes.items()):
            try:
                await self._close_stack(runtime.stack)
            except Exception as exc:
                logger.warning("MCP server %s shutdown failed: %s", name, exc)
                self._record_error(f"{name} shutdown: {exc}")
        self._runtimes.clear()


def _safe_name(value: str) -> str:
    cleaned = _NAME_SAFE.sub("_", value.strip())
    return cleaned.strip("_") or "tool"


def _needs_confirmation(tool_name: str) -> bool:
    lowered = tool_name.lower()
    if any(token in lowered for token in ("read", "list", "get", "search", "fetch")):
        return False
    return True


def mcp_tool_needs_confirmation(tool_name: str) -> bool:
    """Whether an MCP tool exposed to the agent loop requires user confirmation."""
    if not tool_name.startswith("mcp_"):
        return True
    return _needs_confirmation(tool_name)
