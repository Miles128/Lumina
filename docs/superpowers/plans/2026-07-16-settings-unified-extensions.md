# 设置界面重构 + Connector 统一 MCP 扩展架构 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构设置界面为「按配置对象」的四组结构(Agent / 工具与扩展 / 知识库 / 个人),并把 6 个独立 connector(飞书/邮箱/微信读书/小红书/微信公众号/本地网盘)统一改造为「内置 MCP provider」,与用户自建 MCP server 共享 `mcp_{provider}_{tool}` 命名空间,由 `McpManager` 统一加载与暴露,`SyncService` 改为通过 MCP 工具调用拿数据。

**Architecture:**
1. **后端抽象层**:新增 `BuiltinMcpProvider` 协议,每个 connector 实现该协议,暴露 `{source}_status` / `{source}_fetch` 工具;`McpManager` 扩展支持内置 provider 注册(同进程,不走子进程),与 stdio/remote server 统一命名空间。
2. **同步链路**:`SyncService.sync_source` 不再直接调 `BaseConnector.fetch()`,改为 `mcp_manager.call_tool("{source}_fetch")` 拿 `list[MemoryChunk]` JSON,再统一写库;`/api/sync/*` 链路保留。
3. **前端设置**:重写 `settings.js` 的 nav 分组为四组;原 connector 配置卡片从「知识」分组移除,收敛到「工具与扩展 > MCP 服务器」列表中(内置 server 标记 `builtin` 徽章,点击进入配置底层仍走 `/api/settings/platforms/*`);新增 Skill 入口卡片(链接到独立 skills 面板)。
4. **工具注册**:`chat_tool_registry.py` 删除 `connector_tools` 三个工具(`list_connectors`/`connector_status`/`sync_source`),connector 能力统一由 MCP 工具(`mcp_feishu_status` 等)提供;`sync_source` 语义改为调用 `McpManager` 的内置 fetch 工具,保留为一个轻量编排工具。

**Tech Stack:** Python 3.12, FastAPI, 现有 McpManager / SyncService / PlatformConfigStore, 原生 JS(无框架), CSS tokens

**关键决策点(执行前请确认):**
- **D1**:内置 MCP provider 走同进程注册(非子进程),避免 connector 配置(IMAP 账号等)通过 mcp.json env 传递的安全/复杂度问题。配置仍存 `PlatformConfigStore`,provider 启动时读取。
- **D2**:本地文档(`LOCAL_DOCUMENTS`)因走 `LocalDocumentsProfiler`(全量重写 + profile 更新),不改造为 MCP provider,保留在 SyncService 内,前端归到「知识库」分组。
- **D3**:Shibei 已是 service 封装,本期不改造为 MCP,保留在「知识库」分组。
- **D4**:独立 skills 面板(topbar「技能」入口)保持现状,设置界面「工具与扩展」分组提供 Skill 入口卡片(打开 skills 面板),不合并。

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/secretary/agent/mcp_builtin.py` | Create | `BuiltinMcpProvider` 协议 + `BuiltinMcpRegistry` 注册中心 + 6 个 connector provider 实现 |
| `src/secretary/agent/mcp_manager.py` | Modify | 扩展支持内置 provider 注册,统一 `mcp_{provider}_{tool}` 命名空间,`get_tools()` 合并内置与远程 |
| `src/secretary/services/sync.py` | Modify | `sync_source` 改为通过 `McpManager.call_tool("{source}_fetch")` 拿数据;废弃 `build_connectors()` 依赖 |
| `src/secretary/connectors/registry.py` | Modify | 标记 deprecated,保留 `build_connectors` 作为 provider 实现基础(复用 fetch 逻辑) |
| `src/secretary/agent/tools/connector_tools.py` | Modify | `SyncSourceTool` 改为通过 McpManager 调用 fetch;`ListConnectorsTool`/`ConnectorStatusTool` 改为读 MCP provider 元数据 |
| `src/secretary/agent/chat_tool_registry.py` | Modify | 工具注册调整:connector 工具改为读 MCP provider 列表 |
| `src/secretary/api/app.py` | Modify | 新增 `/api/mcp/builtin` 端点(列出内置 provider + 状态);`/api/settings/platforms` 响应增加 `mcp_provider` 字段标识 |
| `desktop/ui/settings.js` | Modify | 重写 `renderNav` 四组结构;新增 MCP 统一管理视图;connector 配置收敛到 MCP 详情 |
| `desktop/ui/chat.css` | Modify | 新增分组样式、内置 MCP 徽章、MCP 统一列表样式 |
| `desktop/ui/i18n.js` | Modify | 新增分组与 MCP 相关 i18n key |
| `tests/agent/test_mcp_builtin.py` | Create | 内置 provider 协议与注册测试 |
| `tests/agent/test_mcp_manager.py` | Modify | 内置 provider 加载与工具暴露测试 |
| `tests/services/test_sync.py` | Modify | sync_source 通过 MCP 调用的测试 |
| `tests/api/test_platform_settings.py` | Modify | `/api/mcp/builtin` 端点测试 |

---

## 阶段 1:后端 — 内置 MCP provider 抽象

### Task 1.1: 定义 BuiltinMcpProvider 协议与注册中心

**Files:**
- Create: `src/secretary/agent/mcp_builtin.py`
- Test: `tests/agent/test_mcp_builtin.py`

- [ ] **Step 1: 写失败测试 — provider 协议与注册**

创建 `tests/agent/test_mcp_builtin.py`:

```python
"""Tests for builtin MCP providers (connector → MCP abstraction)."""
from __future__ import annotations

from pathlib import Path
from secretary.agent.mcp_builtin import (
    BuiltinMcpProvider,
    BuiltinMcpRegistry,
    BuiltinToolSpec,
)


class _FakeProvider(BuiltinMcpProvider):
    name = "fake"
    display_name = "测试源"

    def status(self) -> dict:
        return {"configured": True, "message": "ok", "item_count": 5}

    def tools(self) -> list[BuiltinToolSpec]:
        return [
            BuiltinToolSpec(
                tool_name="status",
                description="fake status",
                input_schema={"type": "object", "properties": {}},
                handler=lambda args: {"ok": True},
            ),
        ]


def test_registry_register_and_list():
    reg = BuiltinMcpRegistry()
    reg.register(_FakeProvider())
    providers = reg.list_providers()
    assert len(providers) == 1
    assert providers[0].name == "fake"


def test_registry_get_tools_namespaced():
    reg = BuiltinMcpRegistry()
    reg.register(_FakeProvider())
    tools = reg.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "mcp_fake_status"


def test_registry_call_tool():
    reg = BuiltinMcpRegistry()
    reg.register(_FakeProvider())
    result = reg.call_tool("mcp_fake_status", {})
    assert result == {"ok": True}


def test_registry_unknown_tool_returns_error():
    reg = BuiltinMcpRegistry()
    reg.register(_FakeProvider())
    result = reg.call_tool("mcp_fake_nonexistent", {})
    assert "error" in result
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/agent/test_mcp_builtin.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'secretary.agent.mcp_builtin'`

- [ ] **Step 3: 实现 BuiltinMcpProvider 协议与注册中心**

创建 `src/secretary/agent/mcp_builtin.py`:

```python
"""Builtin MCP providers — connectors exposed as in-process MCP tools.

Each connector (feishu/email/weread/...) is wrapped as a BuiltinMcpProvider,
registered in BuiltinMcpRegistry, and exposed via McpManager under the
unified namespace ``mcp_{provider}_{tool}`` — identical to remote/stdio MCP
servers. SyncService calls ``mcp_{source}_fetch`` to pull chunks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class BuiltinToolSpec:
    """Declarative spec for a single builtin MCP tool."""

    tool_name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]


class BuiltinMcpProvider(Protocol):
    """A connector exposed as a set of in-process MCP tools.

    Providers share the agent process (no subprocess), so they can read
    PlatformConfigStore directly. Tools are namespaced as ``mcp_{name}_{tool}``.
    """

    name: str
    display_name: str

    def status(self) -> dict[str, Any]:
        """Return configuration status: {configured, message, item_count, last_sync_at?}."""
        ...

    def tools(self) -> list[BuiltinToolSpec]:
        """Return tool specs exposed by this provider."""
        ...


@dataclass
class _RegisteredTool:
    provider_name: str
    tool_name: str
    full_name: str  # mcp_{provider}_{tool}
    spec: BuiltinToolSpec


class BuiltinMcpRegistry:
    """Registry of builtin MCP providers. McpManager reads from this."""

    def __init__(self) -> None:
        self._providers: dict[str, BuiltinMcpProvider] = {}
        self._tools: dict[str, _RegisteredTool] = {}

    def register(self, provider: BuiltinMcpProvider) -> None:
        if provider.name in self._providers:
            raise ValueError(f"Duplicate builtin provider: {provider.name}")
        self._providers[provider.name] = provider
        for spec in provider.tools():
            full_name = f"mcp_{provider.name}_{spec.tool_name}"
            self._tools[full_name] = _RegisteredTool(
                provider_name=provider.name,
                tool_name=spec.tool_name,
                full_name=full_name,
                spec=spec,
            )

    def list_providers(self) -> list[BuiltinMcpProvider]:
        return list(self._providers.values())

    def get_tools(self) -> list[_RegisteredTool]:
        return list(self._tools.values())

    def call_tool(self, full_name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tools.get(full_name)
        if tool is None:
            return {"error": f"Unknown builtin tool: {full_name}"}
        try:
            return tool.spec.handler(arguments)
        except Exception as exc:  # noqa: BLE001 — MCP tool error boundary
            return {"error": f"{type(exc).__name__}: {exc}"}

    def has_tool(self, full_name: str) -> bool:
        return full_name in self._tools
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/agent/test_mcp_builtin.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: 提交**

```bash
git add src/secretary/agent/mcp_builtin.py tests/agent/test_mcp_builtin.py
git commit -m "feat(mcp): add BuiltinMcpProvider protocol and registry"
```

---

### Task 1.2: 把 6 个 connector 改造为 BuiltinMcpProvider

**Files:**
- Modify: `src/secretary/agent/mcp_builtin.py` (追加 provider 实现)
- Modify: `src/secretary/connectors/registry.py` (保留,作为 provider 复用基础)
- Test: `tests/agent/test_mcp_builtin.py` (追加 provider 测试)

- [ ] **Step 1: 写失败测试 — 飞书 provider 暴露 status/fetch 工具**

追加到 `tests/agent/test_mcp_builtin.py`:

```python
from secretary.agent.mcp_builtin import build_builtin_registry
from secretary.core.types import SourceKind


def test_builtin_registry_includes_all_connectors():
    """All 6 connectors must be exposed as builtin providers."""
    reg = build_builtin_registry(settings=None, sync_service=None)
    names = {p.name for p in reg.list_providers()}
    assert names == {"feishu", "email", "weread", "xiaohongshu", "weixin_oa", "cloud_drive"}


def test_builtin_provider_tool_namespace():
    reg = build_builtin_registry(settings=None, sync_service=None)
    tool_names = {t.full_name for t in reg.get_tools()}
    # each connector exposes status + fetch
    for source in ("feishu", "email", "weread", "xiaohongshu", "weixin_oa", "cloud_drive"):
        assert f"mcp_{source}_status" in tool_names
        assert f"mcp_{source}_fetch" in tool_names


def test_builtin_feishu_status_returns_configured_flag():
    reg = build_builtin_registry(settings=None, sync_service=None)
    result = reg.call_tool("mcp_feishu_status", {})
    assert "configured" in result
    assert "message" in result
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/agent/test_mcp_builtin.py::test_builtin_registry_includes_all_connectors -v`
Expected: FAIL — `ImportError: cannot import name 'build_builtin_registry'`

- [ ] **Step 3: 实现 6 个 connector provider**

追加到 `src/secretary/agent/mcp_builtin.py`:

```python
from secretary.connectors.feishu import FeishuConnector
from secretary.connectors.email_imap import EmailConnector
from secretary.connectors.weread import WeReadConnector
from secretary.connectors.xiaohongshu import XiaohongshuConnector
from secretary.connectors.weixin_oa import WeixinOAConnector
from secretary.connectors.cloud_drive import CloudDriveConnector
from secretary.core.types import SourceKind


class _ConnectorProvider:
    """Wrap a BaseConnector as a BuiltinMcpProvider exposing status + fetch."""

    def __init__(self, source: SourceKind, display_name: str, connector_factory: Callable) -> None:
        self.name = source.value
        self.display_name = display_name
        self._source = source
        self._connector_factory = connector_factory

    def _connector(self, settings: Any):
        return self._connector_factory(settings)

    def status(self) -> dict[str, Any]:
        # Read stored health from sync_service if available; else probe connector.
        # Implementation defers to SyncService.get_stored_health for read-only safety.
        raise NotImplementedError("wired in build_builtin_registry")

    def tools(self) -> list[BuiltinToolSpec]:
        return [
            BuiltinToolSpec(
                tool_name="status",
                description=f"{self.display_name} 连接器状态(只读)",
                input_schema={"type": "object", "properties": {}},
                handler=self._status_handler,
            ),
            BuiltinToolSpec(
                tool_name="fetch",
                description=f"拉取 {self.display_name} 数据,返回 list[MemoryChunk] JSON",
                input_schema={"type": "object", "properties": {}},
                handler=self._fetch_handler,
            ),
        ]

    def _status_handler(self, args: dict[str, Any]) -> Any:
        return self.status()

    def _fetch_handler(self, args: dict[str, Any]) -> Any:
        # Defer to the bound sync_service (injected at registry build time).
        raise NotImplementedError("wired in build_builtin_registry")


def build_builtin_registry(settings: Any, sync_service: Any) -> BuiltinMcpRegistry:
    """Build registry with all 6 connector providers.

    ``settings`` and ``sync_service`` are injected so providers can read config
    and trigger fetch without re-instantiating connectors themselves.
    """
    reg = BuiltinMcpRegistry()

    connector_specs = [
        (SourceKind.FEISHU, "飞书", FeishuConnector),
        (SourceKind.EMAIL, "邮箱", EmailConnector),
        (SourceKind.WEREAD, "微信读书", WeReadConnector),
        (SourceKind.XIAOHONGSHU, "小红书", XiaohongshuConnector),
        (SourceKind.WEIXIN_OA, "微信公众号", WeixinOAConnector),
        (SourceKind.CLOUD_DRIVE, "本地网盘目录", CloudDriveConnector),
    ]

    for source, display_name, factory in connector_specs:
        provider = _ConnectorProvider(source, display_name, factory)

        # Wire status: read from sync_service stored health (read-only, no CLI calls).
        def make_status(src: SourceKind):
            def _status(args):
                if sync_service is None:
                    return {"configured": False, "message": "sync service unavailable", "item_count": 0}
                for item in sync_service.get_stored_health():
                    if item.source is src:
                        return {
                            "configured": item.status.value != "not_configured",
                            "status": item.status.value,
                            "message": item.message,
                            "item_count": item.item_count,
                            "last_sync_at": item.last_sync_at.isoformat() if item.last_sync_at else None,
                        }
                return {"configured": False, "message": "未注册", "item_count": 0}
            return _status

        # Wire fetch: call connector.fetch() and serialize chunks to dict.
        def make_fetch(src: SourceKind, fctry):
            def _fetch(args):
                if settings is None:
                    return {"error": "settings unavailable"}
                connector = fctry(settings)
                if not connector.is_configured():
                    return {"error": f"{src.value} 未配置"}
                chunks = connector.fetch()
                return {
                    "source": src.value,
                    "count": len(chunks),
                    "chunks": [
                        {
                            "chunk_id": c.chunk_id,
                            "source": c.source.value,
                            "title": c.title,
                            "content": c.content,
                            "metadata": c.metadata,
                        }
                        for c in chunks
                    ],
                }
            return _fetch

        # Override provider handlers with wired closures.
        provider._status_handler = make_status(source)  # type: ignore[method-assign]
        provider._fetch_handler = make_fetch(source, factory)  # type: ignore[method-assign]
        reg.register(provider)

    return reg
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/agent/test_mcp_builtin.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: 提交**

```bash
git add src/secretary/agent/mcp_builtin.py tests/agent/test_mcp_builtin.py
git commit -m "feat(mcp): wrap 6 connectors as builtin MCP providers"
```

---

### Task 1.3: 扩展 McpManager 支持内置 provider

**Files:**
- Modify: `src/secretary/agent/mcp_manager.py`
- Modify: `tests/agent/test_mcp_manager.py`

- [ ] **Step 1: 写失败测试 — McpManager 合并内置与远程工具**

追加到 `tests/agent/test_mcp_manager.py`:

```python
def test_mcp_manager_exposes_builtin_tools(mcp_manager_with_builtin):
    """McpManager.get_tools() must include builtin provider tools."""
    tools = mcp_manager_with_builtin.get_tools()
    names = {t.name for t in tools}
    assert "mcp_feishu_status" in names
    assert "mcp_feishu_fetch" in names


def test_mcp_manager_call_builtin_tool(mcp_manager_with_builtin):
    result = mcp_manager_with_builtin.call_tool("mcp_feishu_status", {})
    assert "configured" in result


def test_mcp_manager_status_includes_builtin(mcp_manager_with_builtin):
    status = mcp_manager_with_builtin.status()
    assert status["builtin_provider_count"] >= 6
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/agent/test_mcp_manager.py -k builtin -v`
Expected: FAIL

- [ ] **Step 3: 修改 McpManager 接受 BuiltinMcpRegistry**

在 `src/secretary/agent/mcp_manager.py` 的 `McpManager.__init__` 增加 `builtin_registry` 可选参数;`get_tools()` 合并内置 bridge 工具;`call_tool` 优先查内置;`status()` 增加 `builtin_provider_count`。

关键改动(伪代码,执行时按实际行号定位):

```python
# __init__ 签名增加
def __init__(self, config_store, *, builtin_registry: BuiltinMcpRegistry | None = None):
    self._builtin = builtin_registry or BuiltinMcpRegistry()
    ...

# get_tools() 末尾追加
def get_tools(self) -> list[Tool]:
    remote_tools = [t for t in self._bridge_tools if not self._is_skipped(t)]
    builtin_tools = self._build_builtin_bridge_tools()
    return remote_tools + builtin_tools

def _build_builtin_bridge_tools(self) -> list[Tool]:
    tools = []
    for reg_tool in self._builtin.get_tools():
        tools.append(BuiltinBridgeTool(self._builtin, reg_tool))
    return tools

# call_tool 优先查内置
def call_tool(self, full_name, args, timeout=...):
    if self._builtin.has_tool(full_name):
        return self._builtin.call_tool(full_name, args)
    # ... existing remote call logic
```

新增 `BuiltinBridgeTool` 类(类似 `McpBridgeTool`,但 `execute` 调 `builtin_registry.call_tool`):

```python
class BuiltinBridgeTool(Tool):
    def __init__(self, registry, reg_tool):
        self.name = reg_tool.full_name
        self.description = f"[MCP:builtin:{reg_tool.provider_name}] {reg_tool.spec.description}"
        self.needs_confirmation = _needs_confirmation(reg_tool.tool_name)
        self.read_only = not self.needs_confirmation
        self.risk_level = "medium" if self.needs_confirmation else "low"
        self._registry = registry
        self._reg_tool = reg_tool

    def _parameters(self):
        return self._reg_tool.spec.input_schema

    def execute(self, arguments, working_dir):
        result = self._registry.call_tool(self._reg_tool.full_name, arguments)
        if isinstance(result, dict) and "error" in result:
            return ToolResult.failure(result["error"], error_type="builtin_error", retryable=False)
        return json.dumps(result, ensure_ascii=False, default=str)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/agent/test_mcp_manager.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/secretary/agent/mcp_manager.py tests/agent/test_mcp_manager.py
git commit -m "feat(mcp): McpManager merges builtin providers into unified tool namespace"
```

---

### Task 1.4: SyncService 改为通过 MCP fetch 拿数据

**Files:**
- Modify: `src/secretary/services/sync.py`
- Modify: `tests/services/test_sync.py`

- [ ] **Step 1: 写失败测试 — sync_source 通过 MCP fetch**

追加到 `tests/services/test_sync.py`:

```python
def test_sync_source_calls_mcp_fetch(monkeypatch, sync_service_with_mcp):
    """sync_source(feishu) must call mcp_feishu_fetch and upsert returned chunks."""
    calls = []
    def fake_call_tool(name, args, timeout=None):
        calls.append(name)
        if name == "mcp_feishu_fetch":
            return {
                "source": "feishu",
                "count": 1,
                "chunks": [{
                    "chunk_id": "feishu-test-1",
                    "source": "feishu",
                    "title": "测试日程",
                    "content": "测试内容",
                    "metadata": {},
                }],
            }
        return {"error": "unknown"}
    monkeypatch.setattr(sync_service_with_mcp._mcp_manager, "call_tool", fake_call_tool)
    result = sync_service_with_mcp.sync_source(SourceKind.FEISHU)
    assert "mcp_feishu_fetch" in calls
    assert result.inserted >= 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/services/test_sync.py::test_sync_source_calls_mcp_fetch -v`
Expected: FAIL

- [ ] **Step 3: 改造 SyncService.sync_source**

在 `src/secretary/services/sync.py` 中:
- `__init__` 增加 `mcp_manager` 可选参数
- `sync_source` 对 6 个 connector source 改为调 `mcp_manager.call_tool(f"mcp_{source}_fetch", {})`,解析返回的 chunks JSON,重建 `MemoryChunk` 后 `upsert_chunks`
- `LOCAL_DOCUMENTS` 保留原 `_sync_local_documents` 路径不动
- `_get_connector` / `build_connectors` 依赖保留作为 fallback(若 mcp_manager 不可用),但主路径走 MCP

关键改动:

```python
def sync_source(self, source: SourceKind) -> SyncResult:
    if source is SourceKind.LOCAL_DOCUMENTS:
        return self._sync_local_documents()
    if self._mcp_manager is not None and self._mcp_manager._builtin.has_tool(f"mcp_{source.value}_fetch"):
        return self._sync_via_mcp(source)
    # fallback: legacy connector path
    return self._sync_via_connector(source)

def _sync_via_mcp(self, source: SourceKind) -> SyncResult:
    raw = self._mcp_manager.call_tool(f"mcp_{source.value}_fetch", {})
    if isinstance(raw, dict) and "error" in raw:
        health = ConnectorHealth(source=source, status=ConnectorStatus.ERROR, message=raw["error"])
        self._store.update_sync_state(source, health)
        return SyncResult(source=source, health=health, inserted=0)
    chunks = [
        MemoryChunk(
            chunk_id=c["chunk_id"],
            source=SourceKind(c["source"]),
            title=c["title"],
            content=c["content"],
            metadata=c.get("metadata", {}),
        )
        for c in raw.get("chunks", [])
    ]
    inserted = self._store.upsert_chunks(chunks)
    health = ConnectorHealth(
        source=source,
        status=ConnectorStatus.READY,
        message=f"通过 MCP 同步 {inserted} 条",
        last_sync_at=datetime.now(UTC),
        item_count=len(chunks),
    )
    self._store.update_sync_state(source, health)
    return SyncResult(source=source, health=health, inserted=inserted)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/services/test_sync.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/secretary/services/sync.py tests/services/test_sync.py
git commit -m "feat(sync): sync_source pulls data via MCP builtin fetch tools"
```

---

### Task 1.5: 服务装配 — 注入 builtin registry

**Files:**
- Modify: `src/secretary/api/app.py` (`_init_services`)

- [ ] **Step 1: 在 _init_services 中构建 builtin registry 并注入 McpManager 与 SyncService**

在 `src/secretary/api/app.py` 的 `_init_services` (约 385-446 行)中:

```python
from secretary.agent.mcp_builtin import build_builtin_registry

# 构建 builtin registry(注入 settings 与 sync_service,注意循环依赖:先建 sync_service 再建 registry)
builtin_registry = build_builtin_registry(settings=self._settings, sync_service=sync_service)
mcp_manager = McpManager(mcp_store, builtin_registry=builtin_registry)
sync_service.set_mcp_manager(mcp_manager)  # 新增 setter,避免构造期循环
```

注意依赖顺序:`SyncService` 需 `mcp_manager`,`McpManager` 需 `builtin_registry`,`builtin_registry` 需 `sync_service`(读 stored health)。用 setter 打破循环:
- `build_builtin_registry(settings, sync_service=None)` 先建(状态工具降级)
- `McpManager(..., builtin_registry=registry)` 建好
- `sync_service.set_mcp_manager(mcp_manager)` 注入

- [ ] **Step 2: 运行全量测试确认无回归**

Run: `uv run pytest tests/ -x -q`
Expected: PASS(或仅预期的 flaky)

- [ ] **Step 3: 提交**

```bash
git add src/secretary/api/app.py
git commit -m "feat(app): wire builtin MCP registry into McpManager and SyncService"
```

---

## 阶段 2:后端 — connector_tools 收敛

### Task 2.1: connector_tools 改为读 MCP provider 元数据

**Files:**
- Modify: `src/secretary/agent/tools/connector_tools.py`
- Modify: `tests/agent/test_connector_tools.py`

- [ ] **Step 1: 写失败测试 — ListConnectorsTool 读 MCP provider**

追加到 `tests/agent/test_connector_tools.py`:

```python
def test_list_connectors_reads_mcp_providers(mcp_registry_with_providers):
    tool = ListConnectorsTool(registry=mcp_registry_with_providers)
    result = tool.execute({}, Path("/tmp"))
    assert "飞书" in result or "feishu" in result
    assert "邮箱" in result or "email" in result


def test_sync_source_tool_calls_mcp_fetch(monkeypatch, mcp_registry_with_providers):
    tool = SyncSourceTool(mcp_manager=mock_mcp_manager)
    monkeypatch.setattr(mock_mcp_manager, "call_tool", fake_fetch)
    result = tool.execute({"source": "feishu"}, Path("/tmp"))
    assert "同步" in result or "feishu" in result
```

- [ ] **Step 2: 改造 connector_tools.py**

`ListConnectorsTool` / `ConnectorStatusTool` 改为接受 `BuiltinMcpRegistry`,列出 provider 状态(调 `mcp_{source}_status`)。`SyncSourceTool` 改为接受 `mcp_manager`,调 `mcp_{source}_fetch` + 由 SyncService 写库(或直接调 sync_service.sync_source,内部走 MCP)。

保留工具名 `list_connectors` / `connector_status` / `sync_source` 不变,避免 agent 提示词大面积改动;语义不变,只是底层走 MCP。

- [ ] **Step 3: 运行测试确认通过**

Run: `uv run pytest tests/agent/test_connector_tools.py -v`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add src/secretary/agent/tools/connector_tools.py tests/agent/test_connector_tools.py
git commit -m "refactor(tools): connector_tools read MCP builtin provider metadata"
```

---

## 阶段 3:前端 — 设置界面重构

### Task 3.1: 重写设置面板 nav 为四组结构

**Files:**
- Modify: `desktop/ui/settings.js` (`renderNav`)
- Modify: `desktop/ui/i18n.js` (新增分组 key)

- [ ] **Step 1: 修改 renderNav 为四组**

在 `desktop/ui/settings.js` 的 `renderNav` (97-167 行)中,重组为:

```javascript
function renderNav() {
  navEl.innerHTML = "";

  // 组 1:Agent
  const agentGroup = document.createElement("div");
  agentGroup.className = "settings-nav-group";
  agentGroup.innerHTML = `<div class="settings-nav-label">${escapeHtml(t("settings.group.agent"))}</div>`;
  for (const item of [
    { key: "agent_llm", label: t("settings.llm"), status: agentConfig?.status || "not_configured" },
    { key: "agent_soul", label: t("settings.soul"), status: "ready" },
    { key: "agent_memory", label: t("settings.memory"), status: "ready" },
  ]) {
    agentGroup.appendChild(buildNavItem(item));
  }
  navEl.appendChild(agentGroup);

  // 组 2:工具与扩展(MCP + Skill 入口)
  const toolsGroup = document.createElement("div");
  toolsGroup.className = "settings-nav-group";
  toolsGroup.innerHTML = `<div class="settings-nav-label">${escapeHtml(t("settings.group.tools"))}</div>`;
  toolsGroup.appendChild(buildNavItem({
    key: "tools_mcp",
    label: t("settings.mcp"),
    status: mcpStatus?.tool_count ? "ready" : "not_configured",
  }));
  toolsGroup.appendChild(buildNavItem({
    key: "tools_skills",
    label: t("settings.skills"),
    status: "ready",
  }));
  navEl.appendChild(toolsGroup);

  // 组 3:知识库(Shibei + 本地文档,connector 已归到 MCP)
  const knowledgeGroup = document.createElement("div");
  knowledgeGroup.className = "settings-nav-group";
  knowledgeGroup.innerHTML = `<div class="settings-nav-label">${escapeHtml(t("settings.group.knowledge"))}</div>`;
  knowledgeGroup.appendChild(buildNavItem({
    key: "agent_shibei",
    label: t("settings.shibei"),
    status: shibeiConfig?.status || "not_configured",
  }));
  // 本地文档保留(走 LocalDocumentsProfiler,不改造为 MCP)
  const localDocs = platforms.find((p) => p.source === "local_documents");
  if (localDocs) {
    knowledgeGroup.appendChild(buildNavItem(localDocs));
  }
  navEl.appendChild(knowledgeGroup);

  // 组 4:个人
  const personalGroup = document.createElement("div");
  personalGroup.className = "settings-nav-group";
  personalGroup.innerHTML = `<div class="settings-nav-label">${escapeHtml(t("settings.group.personal"))}</div>`;
  for (const item of [
    { key: "profile", label: t("settings.profile") },
    { key: "appearance", label: t("settings.appearance") },
    { key: "about", label: t("settings.about") },
  ]) {
    personalGroup.appendChild(buildNavItem(item));
  }
  navEl.appendChild(personalGroup);
}

function buildNavItem(item) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = `settings-nav-item${activeKey === item.key ? " active" : ""}`;
  btn.dataset.key = item.key;
  const dot = item.status ? `<span class="status-dot ${item.status}" aria-hidden="true"></span>` : "";
  btn.innerHTML = `<span>${escapeHtml(item.label)}</span>${dot}`;
  btn.addEventListener("click", () => selectTab(item.key));
  return btn;
}
```

- [ ] **Step 2: 新增 i18n key**

在 `desktop/ui/i18n.js` 中新增:
- `settings.group.agent` = "Agent" / "Agent"
- `settings.group.tools` = "工具与扩展" / "Tools & Extensions"
- `settings.group.knowledge` = "知识库" / "Knowledge"
- `settings.group.personal` = "个人" / "Personal"
- `settings.skills` = "技能" / "Skills"

- [ ] **Step 3: 手动验证**

启动 desktop,打开设置,确认四个分组显示正确,本地文档仍在知识库组,MCP/Skill 在工具与扩展组。

- [ ] **Step 4: 提交**

```bash
git add desktop/ui/settings.js desktop/ui/i18n.js
git commit -m "feat(ui): regroup settings nav into Agent/Tools/Knowledge/Personal"
```

---

### Task 3.2: 新增 MCP 统一管理视图(含内置 connector)

**Files:**
- Modify: `desktop/ui/settings.js` (新增 `renderToolsMcpPane`)
- Modify: `desktop/ui/chat.css` (新增样式)

- [ ] **Step 1: 新增 renderToolsMcpPane — 统一 MCP 列表**

在 `desktop/ui/settings.js` 中,合并当前 `renderAgentMcpPane` 与 connector 配置为统一视图:

```javascript
function renderToolsMcpPane() {
  const status = mcpStatus || {};
  const builtinProviders = Array.isArray(status.builtin_providers) ? status.builtin_providers : [];
  const remoteServers = (Array.isArray(status.servers) ? status.servers : []).filter(
    (s) => s.enabled !== false,
  );
  const tools = Array.isArray(status.tools) ? status.tools : [];

  contentEl.innerHTML = `
    <div class="settings-pane is-wide">
      <header class="settings-pane-head">
        <h3>${escapeHtml(t("settings.mcp"))}</h3>
        <p>统一管理 MCP 服务器与扩展工具。内置连接器(飞书/邮箱等)与用户自建服务器共享同一命名空间。</p>
      </header>
      <p class="platform-meta">已加载 ${Number(status.tool_count || 0)} 个工具 · 内置 ${builtinProviders.length} · 远程 ${remoteServers.length}</p>

      <h4 class="settings-subtitle">内置连接器</h4>
      <ul class="mcp-builtin-list">${renderBuiltinProviderRows(builtinProviders)}</ul>

      <h4 class="settings-subtitle">远程 / stdio 服务器</h4>
      <ul class="mcp-server-list">${renderServerRows(remoteServers)}</ul>

      <h4 class="settings-subtitle">添加服务器</h4>
      ${renderMcpAddForm()}

      <h4 class="settings-subtitle">工具列表</h4>
      <div class="mcp-tool-table-wrap">
        <table class="mcp-tool-table">
          <thead><tr><th>工具名</th><th>来源</th><th>说明</th></tr></thead>
          <tbody>${renderToolRows(tools)}</tbody>
        </table>
      </div>
      <div id="mcp-feedback" class="platform-feedback" hidden></div>
    </div>
  `;
  bindMcpPaneEvents();
}
```

`renderBuiltinProviderRows` 渲染 6 个内置 provider(飞书/邮箱/微信读书/小红书/微信公众号/本地网盘),每行显示:
- 名称 + `builtin` 徽章
- 状态点(configured/error/not_configured)
- 「配置」按钮(打开对应 connector 配置弹层,底层调 `/api/settings/platforms/{source}`)
- 「同步」按钮(调 `/api/sync/{source}`)

- [ ] **Step 2: 新增内置 provider 配置弹层**

点击内置 provider「配置」按钮时,渲染一个轻量配置弹层(复用现有 `renderField` 逻辑),底层 PUT `/api/settings/platforms/{source}`。对 `cli` 类 connector(飞书/微信读书/小红书)显示 setup_hint + 「测试连接」按钮;对 `form` 类(邮箱/微信公众号/本地网盘)显示字段表单。

- [ ] **Step 3: 新增 chat.css 样式**

```css
.mcp-builtin-list { list-style: none; padding: 0; margin: 0 0 16px; }
.mcp-builtin-row {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 12px; border-bottom: 1px solid var(--border);
}
.mcp-builtin-badge {
  font-size: 11px; padding: 2px 6px; border-radius: 3px;
  background: var(--accent-soft); color: var(--accent);
}
.mcp-builtin-row .mcp-builtin-actions { margin-left: auto; display: flex; gap: 8px; }
```

- [ ] **Step 4: 手动验证**

打开设置 > 工具与扩展 > MCP,确认:
- 内置连接器列表显示 6 个 provider + builtin 徽章
- 点击「配置」可配置 IMAP 账号等
- 点击「同步」触发 `/api/sync/{source}`
- 远程服务器列表与添加表单仍在

- [ ] **Step 5: 提交**

```bash
git add desktop/ui/settings.js desktop/ui/chat.css
git commit -m "feat(ui): unified MCP pane with builtin connector providers"
```

---

### Task 3.3: 新增 Skill 入口卡片

**Files:**
- Modify: `desktop/ui/settings.js` (`renderToolsSkillsPane`)

- [ ] **Step 1: 新增 renderToolsSkillsPane**

```javascript
function renderToolsSkillsPane() {
  contentEl.innerHTML = `
    <div class="settings-pane">
      <header class="settings-pane-head">
        <h3>${escapeHtml(t("settings.skills"))}</h3>
        <p>技能以 SKILL.md 形式挂靠,Agent 按需调用。打开技能管理面板可浏览目录、安装与卸载。</p>
      </header>
      <div class="platform-actions">
        <button class="btn-text save-btn" type="button" id="btn-open-skills-panel">${escapeHtml(t("settings.skills.openManager"))}</button>
      </div>
    </div>
  `;
  document.getElementById("btn-open-skills-panel")?.addEventListener("click", () => {
    closeSettings();
    window.SkillsModule?.open();
  });
}
```

在 `renderContent` 中增加 `tools_skills` 分支调用 `renderToolsSkillsPane`。

- [ ] **Step 2: 手动验证**

设置 > 工具与扩展 > 技能,点击按钮关闭设置并打开 skills 面板。

- [ ] **Step 3: 提交**

```bash
git add desktop/ui/settings.js
git commit -m "feat(ui): add Skill entry card in Tools group"
```

---

### Task 3.4: 移除知识分组中的 connector 卡片

**Files:**
- Modify: `desktop/ui/settings.js` (`renderNav` 已在 Task 3.1 处理)

- [ ] **Step 1: 确认 renderNav 不再遍历 platforms 输出 connector**

Task 3.1 的 `renderNav` 已只把 `local_documents` 加入知识库组,其余 connector 不再单独出现。确认 `renderContent` 对 `platform.source` 的 fallback 分支(233-274 行)仍保留——当用户从内置 provider 配置弹层跳转时仍可渲染单个 platform pane。

- [ ] **Step 2: 手动验证**

设置 > 知识库,只剩 Shibei + 本地文档两项,飞书/邮箱/微信读书/小红书/微信公众号/本地网盘不再出现。

- [ ] **Step 3: 提交**(若需改动)

```bash
git add desktop/ui/settings.js
git commit -m "refactor(ui): remove connector cards from Knowledge group"
```

---

## 阶段 4:API 调整

### Task 4.1: 新增 /api/mcp/builtin 端点

**Files:**
- Modify: `src/secretary/api/app.py`
- Modify: `tests/api/test_platform_settings.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/api/test_platform_settings.py`:

```python
def test_get_mcp_builtin_lists_providers(client):
    resp = client.get("/api/mcp/builtin")
    assert resp.status_code == 200
    data = resp.json()
    names = {p["name"] for p in data["providers"]}
    assert "feishu" in names
    assert "email" in names
    for p in data["providers"]:
        assert "display_name" in p
        assert "configured" in p
        assert "status" in p
```

- [ ] **Step 2: 实现 /api/mcp/builtin**

在 `src/secretary/api/app.py` 中新增:

```python
@app.get("/api/mcp/builtin")
def mcp_builtin_providers():
    providers = []
    for p in mcp_manager._builtin.list_providers():
        status = mcp_manager.call_tool(f"mcp_{p.name}_status", {})
        providers.append({
            "name": p.name,
            "display_name": p.display_name,
            "configured": status.get("configured", False),
            "status": status.get("status", "unknown"),
            "message": status.get("message", ""),
            "item_count": status.get("item_count", 0),
            "last_sync_at": status.get("last_sync_at"),
        })
    return {"providers": providers}
```

- [ ] **Step 3: 运行测试确认通过**

Run: `uv run pytest tests/api/test_platform_settings.py -v`
Expected: PASS

- [ ] **Step 4: 在 /api/mcp/status 响应中增加 builtin_providers 字段**

修改 `mcp_status` 端点,响应里追加 `builtin_providers`(同上结构)与 `builtin_provider_count`,供前端 `renderToolsMcpPane` 一次拉取。

- [ ] **Step 5: 提交**

```bash
git add src/secretary/api/app.py tests/api/test_platform_settings.py
git commit -m "feat(api): add /api/mcp/builtin endpoint + builtin_providers in status"
```

---

## 阶段 5:清理与验证

### Task 5.1: 更新 /api/settings/platforms 响应标识 mcp_provider

**Files:**
- Modify: `src/secretary/api/app.py` (`_build_platform_cards`)
- Modify: `src/secretary/services/platform_config.py` (PLATFORM_DEFINITIONS 增加 `mcp_provider` 标记)

- [ ] **Step 1: 在 PLATFORM_DEFINITIONS 增加 mcp_provider 字段**

对 FEISHU/EMAIL/WEREAD/XIAOHONGSHU/WEIXIN_OA/CLOUD_DRIVE 标记 `mcp_provider=True`;LOCAL_DOCUMENTS 标记 `mcp_provider=False`。

- [ ] **Step 2: _build_platform_cards 透出该字段**

前端据此判断是否在内置 provider 列表中显示「配置」入口。

- [ ] **Step 3: 测试 + 提交**

```bash
uv run pytest tests/api/test_platform_settings.py -v
git add -A
git commit -m "feat(api): mark connector platforms with mcp_provider flag"
```

---

### Task 5.2: 全量测试与回归

- [ ] **Step 1: 运行后端全量测试**

Run: `uv run pytest`
Expected: 全部 PASS(修复因重构导致的 import/路径问题)

- [ ] **Step 2: 运行 ruff + mypy**

Run: `uv run ruff check src tests && uv run mypy src`
Expected: 无新增错误

- [ ] **Step 3: 启动 desktop 手动回归**

```bash
cd desktop && npm start
```

验证清单:
- [ ] 设置面板四组结构正确
- [ ] MCP 统一管理视图显示 6 内置 + 远程服务器
- [ ] 内置 provider 可配置 + 可同步
- [ ] Skill 入口可打开 skills 面板
- [ ] 知识库组只剩 Shibei + 本地文档
- [ ] Agent 对话中 `list_connectors` 工具仍可用(底层走 MCP)
- [ ] `sync_source feishu` 仍可同步(底层走 MCP fetch)
- [ ] 现有 MCP server(filesystem 等)仍正常加载

- [ ] **Step 4: 端到端 smoke 测试**

Run: `uv run pytest tests/e2e/ -x`
Expected: PASS

- [ ] **Step 5: 最终提交**

```bash
git add -A
git commit -m "test: full regression for settings refactor + unified MCP extensions"
```

---

## 自检清单

- [ ] **Spec 覆盖**:
  - 设置界面重新做 → 阶段 3(四组结构 + MCP 统一视图 + Skill 入口)
  - MCP/skill 统一到设置 → 阶段 3(MCP 在工具组)+ Task 3.3(Skill 入口)
  - 各个单独接口统一走 MCP → 阶段 1(connector 改 builtin MCP provider)+ 阶段 2(connector_tools 收敛)
- [ ] **Placeholder 扫描**:无 TBD/TODO,关键代码均给出
- [ ] **类型一致性**:`BuiltinMcpProvider` / `BuiltinToolSpec` / `BuiltinMcpRegistry` 在所有任务中命名一致;`mcp_{source}_status` / `mcp_{source}_fetch` 命名一致
- [ ] **风险点**:
  - 循环依赖(SyncService ↔ McpManager ↔ builtin_registry)用 setter 打破
  - `_SKIP_SERVERS={"filesystem"}` 过滤逻辑需确认不影响内置 provider(内置 provider 不在 _SKIP_SERVERS 中)
  - `sync_routing.py` 关键词表与 PLATFORM_DEFINITIONS 仍一致,本期不动

## 执行顺序建议

阶段 1(后端抽象)→ 阶段 2(工具收敛)→ 阶段 4(API)→ 阶段 3(前端)→ 阶段 5(验证)。
前端依赖后端 API 字段,故阶段 4 须先于阶段 3 完成。
