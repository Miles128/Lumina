"""MCP configuration and status routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from secretary.agent.mcp_manager import McpManager
from secretary.api.deps import build_builtin_provider_summaries
from secretary.api.schemas import McpQuickstartFilesystemRequest, McpServerUpsertRequest
from secretary.services.mcp_config import McpConfigStore, McpServerConfig

router = APIRouter(tags=["mcp"])


@router.get("/api/mcp/status")
def mcp_status(request: Request) -> dict[str, object]:
    manager: McpManager = request.app.state.mcp_manager
    data = manager.status()
    data["builtin_providers"] = build_builtin_provider_summaries(manager)
    return data


@router.get("/api/mcp/builtin")
def mcp_builtin_providers(request: Request) -> dict[str, object]:
    manager: McpManager = request.app.state.mcp_manager
    return {"providers": build_builtin_provider_summaries(manager)}


@router.post("/api/mcp/reload")
def mcp_reload(request: Request) -> dict[str, object]:
    manager: McpManager = request.app.state.mcp_manager
    manager.reload()
    return manager.status()


@router.get("/api/mcp/servers")
def mcp_servers(request: Request) -> dict[str, object]:
    store: McpConfigStore = request.app.state.mcp_config_store
    return {"servers": store.list_view()}


@router.post("/api/mcp/servers")
def mcp_upsert_server(request: Request, body: McpServerUpsertRequest) -> dict[str, object]:
    store: McpConfigStore = request.app.state.mcp_config_store
    manager: McpManager = request.app.state.mcp_manager
    command = body.command.strip()
    url = body.url.strip()
    transport = (body.transport or "stdio").strip().lower() or "stdio"
    if transport in {"http", "streamable-http"}:
        transport = "streamable_http"
    if not command and not url:
        raise HTTPException(status_code=400, detail="需要 command（stdio）或 url（远程）")
    if command and url:
        raise HTTPException(status_code=400, detail="command 与 url 只能二选一")
    if url and transport == "stdio":
        transport = "streamable_http"
    if command:
        transport = "stdio"
    try:
        store.upsert_server(
            body.name.strip(),
            McpServerConfig(
                command=command,
                args=body.args,
                env=body.env,
                url=url,
                transport=transport,
                headers=body.headers,
                enabled=body.enabled,
                timeout=body.timeout,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    manager.reload()
    return manager.status()


@router.delete("/api/mcp/servers/{name}")
def mcp_delete_server(request: Request, name: str) -> dict[str, object]:
    store: McpConfigStore = request.app.state.mcp_config_store
    manager: McpManager = request.app.state.mcp_manager
    if not store.remove_server(name):
        raise HTTPException(status_code=404, detail="服务器不存在")
    manager.reload()
    return manager.status()


@router.post("/api/mcp/import-hermes")
def mcp_import_hermes(request: Request) -> dict[str, object]:
    store: McpConfigStore = request.app.state.mcp_config_store
    manager: McpManager = request.app.state.mcp_manager
    added = store.import_from_hermes()
    manager.reload()
    status = manager.status()
    status["imported_count"] = added
    return status


@router.post("/api/mcp/quickstart/filesystem")
def mcp_quickstart_filesystem(
    request: Request,
    body: McpQuickstartFilesystemRequest | None = None,
) -> dict[str, object]:
    store: McpConfigStore = request.app.state.mcp_config_store
    manager: McpManager = request.app.state.mcp_manager
    root_raw = body.root.strip() if body and body.root else ""
    root = Path(root_raw).expanduser() if root_raw else Path.home() / "Documents"
    try:
        added = store.add_filesystem_server(root)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    manager.reload()
    status = manager.status()
    status["added"] = added
    status["root"] = str(root.expanduser().resolve())
    return status


