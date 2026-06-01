"""FastAPI application."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from secretary.agent.chat_service import ChatResult, ChatService
from secretary.agent.mcp_manager import McpManager
from secretary.agent.progress_hub import ProgressHub
from secretary.agent.llm_client import LlmUsage, chat_completion, llm_usage_scope
from secretary.agent.llm_config import resolve_llm_config
from secretary.agent.skills import SkillManager
from secretary.agent.soul import load_soul, save_soul
from secretary.config import settings
from secretary.connectors.base import BaseConnector
from secretary.core.types import ConnectorHealth, ConnectorStatus, SourceKind
from secretary.exceptions import AgentError, IngestError
from secretary.memory.db import MemoryStore
from secretary.memory.graph import GraphBuilder
from secretary.memory.kb import KnowledgeWorkspace
from secretary.services.briefing import BriefingService
from secretary.services.local_documents_profiler import LocalDocumentsProfiler
from secretary.services.memory_summarizer import MemorySummarizerService
from secretary.services.mcp_config import McpConfigStore, McpServerConfig
from secretary.services.scheduled_think import ScheduledThinkService
from secretary.services.scheduler import BackgroundScheduler
from secretary.services.platform_config import (
    PLATFORM_DEFINITIONS,
    PlatformConfigStore,
    mask_secrets,
)
from secretary.services.profile_service import ProfileService
from secretary.services.sync import SyncService
from secretary.services.agent_config import PROVIDER_PRESETS, AgentConfigStore
from secretary.services.file_auth import FileAuthService
from secretary.services.user_profile_store import UserProfileStore
from secretary.utils.messages import format_connector_message


class HealthResponse(BaseModel):
    source: str
    status: str
    message: str
    last_sync_at: datetime | None = None
    item_count: int = 0


class SyncResponse(BaseModel):
    source: str
    inserted: int
    status: str
    message: str


class ProfileResponse(BaseModel):
    generated_at: datetime
    markdown: str
    auto_markdown: str
    user_markdown: str
    is_user_edited: bool
    sections: list[dict[str, str | int]]


class ProfileUpdateRequest(BaseModel):
    markdown: str = Field(max_length=100_000)


class MemorySearchResponse(BaseModel):
    query: str
    results: list[dict[str, str]]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    trace_id: str = Field(default="", max_length=64)
    location_city: str = Field(default="", max_length=64)


class LocationReverseRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class LocationReverseResponse(BaseModel):
    city: str = ""


class ChatResponse(BaseModel):
    reply: str
    profile_excerpt: str
    used_tools: list[str] = []
    total_steps: int = 1
    route: str = ""
    needs_confirmation: bool = False
    confirmation_description: str = ""
    confirmation_action_id: str = ""
    confirmation_risk_level: str = ""
    confirmation_kind: str = ""
    allow_permanent_read: bool = False
    allow_session_write: bool = False
    grounding_verified: bool = True
    grounding_note: str = ""
    files_read: list[str] = []
    usage_prompt_tokens: int = 0
    usage_completion_tokens: int = 0
    usage_total_tokens: int = 0


class ConfirmActionRequest(BaseModel):
    action_id: str = Field(min_length=1)
    approved: bool
    grant_permanent_read: bool = False
    grant_session_write: bool = False
    trace_id: str = Field(default="", max_length=64)


class GraphResponse(BaseModel):
    nodes: list[dict[str, object]]
    edges: list[dict[str, str]]
    layout: str


class NoteListResponse(BaseModel):
    notes: list[dict[str, str]]


class NoteDetailResponse(BaseModel):
    path: str
    content: str


class NoteUpdateRequest(BaseModel):
    path: str = Field(min_length=1)
    content: str = Field(max_length=500_000)


class BriefingResponse(BaseModel):
    markdown: str
    generated_at: str


class McpServerUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=48)
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    timeout: int = Field(default=120, ge=5, le=600)


class BackgroundTasksResponse(BaseModel):
    think_enabled: bool
    think_interval_hours: int
    last_think_at: str
    last_think_markdown: str
    memory_summary_enabled: bool
    memory_summary_hour: int
    last_summary_date: str
    last_summary: str


class PlatformFieldResponse(BaseModel):
    key: str
    label: str
    field_type: str
    placeholder: str
    value: str | int | bool


class PlatformCardResponse(BaseModel):
    source: str
    name: str
    description: str
    kind: str
    setup_hint: str
    status: str
    status_message: str
    fields: list[PlatformFieldResponse]


class PlatformUpdateRequest(BaseModel):
    values: dict[str, str | int | bool]


class SkillRecordResponse(BaseModel):
    name: str
    description: str
    path: str
    source_key: str
    source_label: str
    source_root: str
    origin_path: str
    install_mode: str
    link_target: str
    status: str
    category: str
    tags: list[str]
    installed: bool


class SkillSourceResponse(BaseModel):
    key: str
    label: str
    path: str
    available: bool
    count: int = 0


class SkillInstallAllResponse(BaseModel):
    installed: int
    skipped: int
    failed: list[str]
    message: str


class SkillInstallRequest(BaseModel):
    source_path: str = Field(min_length=1, max_length=4096)
    target_name: str = Field(default="", max_length=120)
    install_mode: str = "link"


class SkillUninstallRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class SkillCategoryUpdateRequest(BaseModel):
    category: str = Field(min_length=1, max_length=60)
    tags: list[str] = []


class SoulResponse(BaseModel):
    markdown: str
    path: str


class SoulUpdateRequest(BaseModel):
    markdown: str = Field(max_length=50_000)


class AgentConfigResponse(BaseModel):
    provider: str
    api_key_masked: str
    base_url: str
    model: str
    temperature: float
    max_history_turns: int
    use_hermes_fallback: bool
    response_style: str
    shell_working_dir: str = ""
    status: str
    status_message: str
    active_source: str
    providers: list[dict[str, str]]


class AgentConfigUpdateRequest(BaseModel):
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    temperature: float | None = None
    max_history_turns: int | None = None
    use_hermes_fallback: bool | None = None
    response_style: str = ""
    shell_working_dir: str | None = None


class McpQuickstartFilesystemRequest(BaseModel):
    root: str = ""


class AgentTestResponse(BaseModel):
    status: str
    message: str
    model: str
    source: str


DESKTOP_UI_DIR = Path(__file__).resolve().parents[3] / "desktop" / "ui"


def _to_chat_response(result: ChatResult, usage: LlmUsage | None = None) -> ChatResponse:
    pending = result.pending_confirmation
    usage_stats = usage or LlmUsage()
    return ChatResponse(
        reply=result.reply,
        profile_excerpt=result.profile_excerpt,
        used_tools=result.used_tools or [],
        total_steps=result.total_steps,
        route=result.route,
        needs_confirmation=pending is not None,
        confirmation_description=pending.description if pending else "",
        confirmation_action_id=pending.action_id if pending else "",
        confirmation_risk_level=pending.risk_level if pending else "",
        confirmation_kind=result.confirmation_kind,
        allow_permanent_read=result.allow_permanent_read,
        allow_session_write=result.allow_session_write,
        grounding_verified=result.grounding_verified,
        grounding_note=result.grounding_note,
        files_read=list(result.files_read or []),
        usage_prompt_tokens=usage_stats.prompt_tokens,
        usage_completion_tokens=usage_stats.completion_tokens,
        usage_total_tokens=usage_stats.total_tokens,
    )


def _init_services() -> dict[str, object]:
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    platform_store = PlatformConfigStore(settings.resolved_data_dir() / "platforms.json")
    sync_service = SyncService(settings, store)
    local_documents_profiler = LocalDocumentsProfiler(settings)
    user_profile_store = UserProfileStore(settings.resolved_data_dir() / "user_profile.md")
    profile_service = ProfileService(settings, store, local_documents_profiler, user_profile_store)
    agent_config_store = AgentConfigStore(settings.resolved_data_dir() / "agent.json")
    agent_config_store.apply_to_settings(settings)
    skill_manager = SkillManager(settings.resolved_data_dir())
    file_auth = FileAuthService(settings.resolved_data_dir() / "file_auth.json")
    mcp_config_store = McpConfigStore(settings.resolved_data_dir() / "mcp.json")
    mcp_manager = McpManager(mcp_config_store)
    if settings.mcp_auto_filesystem:
        preferred_root: Path | None = None
        shell_raw = agent_config_store.load().shell_working_dir.strip()
        if shell_raw:
            shell_path = Path(shell_raw).expanduser()
            if shell_path.is_dir():
                preferred_root = shell_path
        if mcp_config_store.ensure_filesystem_server(preferred_root):
            mcp_manager.reload()
    progress_hub = ProgressHub()
    chat_service = ChatService(
        settings,
        store,
        profile_service,
        skill_manager,
        agent_config_store,
        sync_service=sync_service,
        file_auth=file_auth,
        mcp_manager=mcp_manager,
    )
    workspace = KnowledgeWorkspace(settings.resolved_data_dir() / "workspace")
    workspace.ensure_layout()
    return {
        "store": store,
        "platform_store": platform_store,
        "sync_service": sync_service,
        "profile_service": profile_service,
        "agent_config_store": agent_config_store,
        "skill_manager": skill_manager,
        "chat_service": chat_service,
        "mcp_manager": mcp_manager,
        "mcp_config_store": mcp_config_store,
        "progress_hub": progress_hub,
        "workspace": workspace,
    }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not hasattr(app.state, "store"):
        for key, value in _init_services().items():
            setattr(app.state, key, value)
    app.state.profile_service.persist_after_sync()

    shutdown = asyncio.Event()
    scheduler_task: asyncio.Task[None] | None = None
    if (
        settings.auto_sync_enabled
        or settings.briefing_enabled
        or settings.think_enabled
        or settings.memory_summary_enabled
    ):
        briefing_service = BriefingService(settings, app.state.store)
        hermes = app.state.chat_service.hermes_memory
        think_service = ScheduledThinkService(
            settings,
            hermes,
            app.state.profile_service,
            app.state.agent_config_store,
        )
        memory_summarizer = MemorySummarizerService(
            settings,
            hermes,
            app.state.agent_config_store,
        )
        scheduler = BackgroundScheduler(
            settings,
            app.state.sync_service,
            app.state.profile_service,
            briefing_service,
            think_service=think_service,
            memory_summarizer=memory_summarizer,
        )
        scheduler_task = asyncio.create_task(scheduler.run_until_stopped(shutdown))

    try:
        yield
    finally:
        shutdown.set()
        if scheduler_task is not None:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
        if hasattr(app.state, "mcp_manager"):
            app.state.mcp_manager.shutdown()


app = FastAPI(title="Lumina", version="0.1.0", lifespan=lifespan)

for key, value in _init_services().items():
    setattr(app.state, key, value)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8765",
        "http://localhost:8765",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _svc(request: Request) -> object:
    return request.app.state


def _build_progress_callback(request: Request, trace_id: str):
    if not trace_id:
        return None
    hub: ProgressHub = request.app.state.progress_hub
    hub.open(trace_id)

    def callback(event) -> None:
        hub.publish(trace_id, event)

    return callback


def _finish_progress(request: Request, trace_id: str) -> None:
    if not trace_id:
        return
    request.app.state.progress_hub.close(trace_id)


@app.get("/api/mcp/status")
def mcp_status(request: Request) -> dict[str, object]:
    manager: McpManager = request.app.state.mcp_manager
    return manager.status()


@app.post("/api/mcp/reload")
def mcp_reload(request: Request) -> dict[str, object]:
    manager: McpManager = request.app.state.mcp_manager
    manager.reload()
    return manager.status()


@app.get("/api/mcp/servers")
def mcp_servers(request: Request) -> dict[str, object]:
    store: McpConfigStore = request.app.state.mcp_config_store
    return {"servers": store.list_view()}


@app.post("/api/mcp/servers")
def mcp_upsert_server(request: Request, body: McpServerUpsertRequest) -> dict[str, object]:
    store: McpConfigStore = request.app.state.mcp_config_store
    manager: McpManager = request.app.state.mcp_manager
    try:
        store.upsert_server(
            body.name.strip(),
            McpServerConfig(
                command=body.command.strip(),
                args=body.args,
                env=body.env,
                enabled=body.enabled,
                timeout=body.timeout,
                transport="stdio",
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    manager.reload()
    return manager.status()


@app.delete("/api/mcp/servers/{name}")
def mcp_delete_server(request: Request, name: str) -> dict[str, object]:
    store: McpConfigStore = request.app.state.mcp_config_store
    manager: McpManager = request.app.state.mcp_manager
    if not store.remove_server(name):
        raise HTTPException(status_code=404, detail="服务器不存在")
    manager.reload()
    return manager.status()


@app.post("/api/mcp/import-hermes")
def mcp_import_hermes(request: Request) -> dict[str, object]:
    store: McpConfigStore = request.app.state.mcp_config_store
    manager: McpManager = request.app.state.mcp_manager
    added = store.import_from_hermes()
    manager.reload()
    status = manager.status()
    status["imported_count"] = added
    return status


@app.post("/api/mcp/quickstart/filesystem")
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


@app.get("/api/agent/background")
def agent_background_status(request: Request) -> BackgroundTasksResponse:
    data_dir = settings.resolved_data_dir()
    think = ScheduledThinkService.load_latest(data_dir) or {}
    summary = MemorySummarizerService.load_latest(data_dir) or {}
    return BackgroundTasksResponse(
        think_enabled=settings.think_enabled,
        think_interval_hours=settings.think_interval_hours,
        last_think_at=str(think.get("last_run_at", "")),
        last_think_markdown=str(think.get("markdown", "")),
        memory_summary_enabled=settings.memory_summary_enabled,
        memory_summary_hour=settings.memory_summary_hour,
        last_summary_date=str(summary.get("last_summary_date", "")),
        last_summary=str(summary.get("summary", "")),
    )


@app.get("/api/health")
def get_health(request: Request) -> list[HealthResponse]:
    sync_service: SyncService = _svc(request).sync_service
    return [
        HealthResponse(
            source=item.source.value,
            status=item.status.value,
            message=format_connector_message(item.message),
            last_sync_at=item.last_sync_at,
            item_count=item.item_count,
        )
        for item in sync_service.get_stored_health()
    ]


@app.post("/api/sync")
async def sync_all(request: Request) -> list[SyncResponse]:
    sync_service: SyncService = _svc(request).sync_service
    results = await asyncio.to_thread(sync_service.sync_all, include_browser_sources=True)
    return [
        SyncResponse(
            source=result.source.value,
            inserted=result.inserted,
            status=result.health.status.value,
            message=result.health.message,
        )
        for result in results
    ]


@app.post("/api/sync/{source}")
async def sync_one(source: SourceKind, request: Request) -> SyncResponse:
    sync_service: SyncService = _svc(request).sync_service
    result = await asyncio.to_thread(sync_service.sync_source, source)
    return SyncResponse(
        source=result.source.value,
        inserted=result.inserted,
        status=result.health.status.value,
        message=result.health.message,
    )


@app.get("/api/profile")
def get_profile(request: Request) -> ProfileResponse:
    profile_service: ProfileService = _svc(request).profile_service
    view = profile_service.get_view()
    return ProfileResponse(
        generated_at=view.generated_at,
        markdown=view.markdown,
        auto_markdown=view.auto_markdown,
        user_markdown=view.user_markdown,
        is_user_edited=view.is_user_edited,
        sections=view.sections,
    )


@app.put("/api/profile")
def update_profile(request: Request, body: ProfileUpdateRequest) -> ProfileResponse:
    profile_service: ProfileService = _svc(request).profile_service
    view = profile_service.save_user_markdown(body.markdown)
    return ProfileResponse(
        generated_at=view.generated_at,
        markdown=view.markdown,
        auto_markdown=view.auto_markdown,
        user_markdown=view.user_markdown,
        is_user_edited=view.is_user_edited,
        sections=view.sections,
    )


@app.delete("/api/profile/user")
def reset_profile_user(request: Request) -> ProfileResponse:
    profile_service: ProfileService = _svc(request).profile_service
    view = profile_service.reset_user_markdown()
    return ProfileResponse(
        generated_at=view.generated_at,
        markdown=view.markdown,
        auto_markdown=view.auto_markdown,
        user_markdown=view.user_markdown,
        is_user_edited=view.is_user_edited,
        sections=view.sections,
    )


@app.get("/api/memory/search")
def search_memory(q: str, limit: int = 10, request: Request = None) -> MemorySearchResponse:
    store: MemoryStore = _svc(request).store
    chunks = store.search(q, limit=limit)
    return MemorySearchResponse(
        query=q,
        results=[
            {
                "chunk_id": chunk.chunk_id,
                "source": chunk.source.value,
                "title": chunk.title,
                "content": chunk.content[:400],
            }
            for chunk in chunks
        ],
    )


@app.get("/api/chat/progress/{trace_id}")
async def chat_progress(request: Request, trace_id: str) -> StreamingResponse:
    hub: ProgressHub = request.app.state.progress_hub
    return StreamingResponse(
        hub.stream(trace_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/api/identity/author")
def identity_author() -> dict[str, str]:
    from secretary.agent.identity import get_author_reply

    return {"reply": get_author_reply()}


@app.get("/api/identity/intro")
def identity_intro() -> dict[str, str]:
    from secretary.agent.identity import get_identity_reply

    return {"reply": get_identity_reply()}


@app.post("/api/location/reverse")
def reverse_location(body: LocationReverseRequest) -> LocationReverseResponse:
    from secretary.services.geolocation import reverse_geocode_city

    city = reverse_geocode_city(body.lat, body.lng) or ""
    return LocationReverseResponse(city=city)


@app.post("/api/chat")
def chat(request: Request, body: ChatRequest) -> ChatResponse:
    chat_service: ChatService = _svc(request).chat_service
    message = body.message.strip()
    author_turn = chat_service.is_author_turn(message)
    identity_turn = chat_service.is_identity_turn(message)
    trace_id = "" if (author_turn or identity_turn) else body.trace_id.strip()
    progress = _build_progress_callback(request, trace_id)
    location_city = body.location_city.strip()
    try:
        with llm_usage_scope() as usage:
            result = chat_service.reply(
                message,
                progress_callback=progress,
                location_city=location_city or None,
            )
        return _to_chat_response(result, usage)
    finally:
        _finish_progress(request, trace_id)


@app.post("/api/chat/confirm")
def confirm_action(request: Request, body: ConfirmActionRequest) -> ChatResponse:
    chat_service: ChatService = _svc(request).chat_service
    trace_id = body.trace_id.strip()
    progress = _build_progress_callback(request, trace_id)
    try:
        with llm_usage_scope() as usage:
            result = chat_service.confirm_action(
                body.approved,
                grant_permanent_read=body.grant_permanent_read,
                grant_session_write=body.grant_session_write,
                progress_callback=progress,
            )
        return _to_chat_response(result, usage)
    finally:
        _finish_progress(request, trace_id)


@app.delete("/api/chat/history")
def clear_chat_history(request: Request) -> dict[str, str]:
    chat_service: ChatService = _svc(request).chat_service
    chat_service.clear_history()
    return {"status": "ok"}


@app.get("/api/memory/durable")
def get_durable_memory(request: Request) -> dict[str, str]:
    chat_service: ChatService = _svc(request).chat_service
    hermes = chat_service.hermes_memory
    return {
        "memory_md": hermes.read_memory_md(),
        "user_md": hermes.read_user_md(),
    }


@app.put("/api/memory/durable")
def update_durable_memory(
    request: Request, body: dict[str, str]
) -> dict[str, str]:
    chat_service: ChatService = _svc(request).chat_service
    hermes = chat_service.hermes_memory
    if "memory_md" in body:
        hermes.write_memory_md(body["memory_md"])
    if "user_md" in body:
        hermes.write_user_md(body["user_md"])
    return {
        "memory_md": hermes.read_memory_md(),
        "user_md": hermes.read_user_md(),
    }


@app.get("/api/memory/sessions/search")
def search_sessions(q: str, limit: int = 10, request: Request = None) -> dict[str, object]:
    chat_service: ChatService = _svc(request).chat_service
    results = chat_service.hermes_memory.search_sessions(q, limit=limit)
    return {"query": q, "results": results}


@app.get("/api/memory/episodes/search")
def search_episodes(q: str, limit: int = 5, request: Request = None) -> dict[str, object]:
    chat_service: ChatService = _svc(request).chat_service
    results = chat_service.hermes_memory.search_episodes(q, limit=limit)
    return {"query": q, "results": results}


class WebSearchResponse(BaseModel):
    query: str
    engine: str
    results: list[dict[str, str]]


@app.get("/api/web/search")
async def web_search(q: str, engine: str = "bing", limit: int = 5) -> WebSearchResponse:
    from secretary.agent.web_search import run_search

    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="empty query")

    limit = min(limit, 8)
    import asyncio

    try:
        results, used_engine = await asyncio.to_thread(run_search, query, engine.lower(), limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return WebSearchResponse(
        query=query,
        engine=used_engine,
        results=[r.to_dict() for r in results],
    )


@app.get("/api/agent/soul")
def get_agent_soul() -> SoulResponse:
    data_dir = settings.resolved_data_dir()
    return SoulResponse(markdown=load_soul(data_dir), path=str(data_dir / "SOUL.md"))


@app.get("/api/agent/soul/hermes")
def get_hermes_soul() -> SoulResponse:
    path = Path.home() / ".hermes" / "SOUL.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Hermes SOUL.md 不存在")
    return SoulResponse(markdown=path.read_text(encoding="utf-8"), path=str(path))


@app.put("/api/agent/soul")
def update_agent_soul(body: SoulUpdateRequest) -> SoulResponse:
    path = save_soul(settings.resolved_data_dir(), body.markdown)
    return SoulResponse(markdown=load_soul(settings.resolved_data_dir()), path=str(path))


@app.get("/api/agent/config")
def get_agent_config(request: Request) -> AgentConfigResponse:
    agent_config_store: AgentConfigStore = _svc(request).agent_config_store
    view = agent_config_store.get_view(settings)
    providers = [
        {"key": key, "label": preset["label"], "base_url": preset["base_url"], "model": preset["model"]}
        for key, preset in PROVIDER_PRESETS.items()
    ]
    return AgentConfigResponse(
        provider=view.provider,
        api_key_masked=view.api_key_masked or ("********" if view.api_key else ""),
        base_url=view.base_url,
        model=view.model,
        temperature=view.temperature,
        max_history_turns=view.max_history_turns,
        use_hermes_fallback=view.use_hermes_fallback,
        response_style=view.response_style,
        shell_working_dir=view.shell_working_dir,
        status=view.status,
        status_message=view.status_message,
        active_source=view.active_source,
        providers=providers,
    )


@app.put("/api/agent/config")
def update_agent_config(request: Request, body: AgentConfigUpdateRequest) -> AgentConfigResponse:
    agent_config_store: AgentConfigStore = _svc(request).agent_config_store
    payload: dict[str, object] = {}
    if body.provider:
        payload["provider"] = body.provider.strip()
    if body.api_key:
        payload["api_key"] = body.api_key.strip()
    if body.base_url:
        payload["base_url"] = body.base_url.strip()
    if body.model:
        payload["model"] = body.model.strip()
    if body.temperature is not None:
        payload["temperature"] = body.temperature
    if body.max_history_turns is not None:
        payload["max_history_turns"] = body.max_history_turns
    if body.use_hermes_fallback is not None:
        payload["use_hermes_fallback"] = body.use_hermes_fallback
    if body.response_style in {"standard", "brief"}:
        payload["response_style"] = body.response_style.strip()
    if body.shell_working_dir is not None:
        payload["shell_working_dir"] = body.shell_working_dir.strip()
    agent_config_store.update(payload)
    agent_config_store.apply_to_settings(settings)
    return get_agent_config(request)


@app.post("/api/agent/config/import-hermes")
def import_agent_config_from_hermes(request: Request) -> AgentConfigResponse:
    agent_config_store: AgentConfigStore = _svc(request).agent_config_store
    try:
        agent_config_store.import_from_hermes()
    except AgentError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    agent_config_store.apply_to_settings(settings)
    return get_agent_config(request)


@app.post("/api/agent/config/test")
def test_agent_config(request: Request) -> AgentTestResponse:
    agent_config_store: AgentConfigStore = _svc(request).agent_config_store
    config = resolve_llm_config(settings, agent_config_store)
    if config is None:
        raise HTTPException(status_code=400, detail="未配置 API Key。请保存大模型设置或开启 Hermes 回退。")
    try:
        reply = chat_completion(
            config,
            [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Reply with exactly: OK"},
            ],
            timeout=30.0,
            temperature=0.0,
        )
    except AgentError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    preview = reply.strip().replace("\n", " ")
    if len(preview) > 80:
        preview = preview[:80] + "…"
    return AgentTestResponse(
        status="ready",
        message=f"连接成功：{preview}",
        model=config.model,
        source=config.source,
    )


@app.get("/api/skills/sources")
def list_skill_sources(request: Request) -> list[SkillSourceResponse]:
    skill_manager: SkillManager = _svc(request).skill_manager
    return [SkillSourceResponse(**item) for item in skill_manager.list_sources()]


@app.get("/api/skills/categories")
def list_skill_categories(request: Request) -> dict[str, list[str]]:
    skill_manager: SkillManager = _svc(request).skill_manager
    return {"categories": skill_manager.categories()}


@app.get("/api/skills/catalog")
def list_skill_catalog(source: str | None = None, request: Request = None) -> list[SkillRecordResponse]:
    skill_manager: SkillManager = _svc(request).skill_manager
    records = skill_manager.catalog(source_key=source)
    return [
        SkillRecordResponse(
            name=item.name,
            description=item.description,
            path=item.path,
            source_key=item.source_key,
            source_label=item.source_label,
            source_root=item.source_root,
            origin_path=item.origin_path,
            install_mode=item.install_mode,
            link_target=item.link_target,
            status=item.status,
            category=item.category,
            tags=list(item.tags),
            installed=item.installed,
        )
        for item in records
    ]


@app.get("/api/skills/installed")
def list_installed_skills(request: Request) -> list[SkillRecordResponse]:
    skill_manager: SkillManager = _svc(request).skill_manager
    records = skill_manager.list_installed()
    return [
        SkillRecordResponse(
            name=item.name,
            description=item.description,
            path=item.path,
            source_key=item.source_key,
            source_label=item.source_label,
            source_root=item.source_root,
            origin_path=item.origin_path,
            install_mode=item.install_mode,
            link_target=item.link_target,
            status=item.status,
            category=item.category,
            tags=list(item.tags),
            installed=item.installed,
        )
        for item in records
    ]


@app.post("/api/skills/install-all")
def install_all_skills(
    source: str | None = None,
    install_mode: str = "link",
    request: Request = None,
) -> SkillInstallAllResponse:
    skill_manager: SkillManager = _svc(request).skill_manager
    key = source.strip() if source else None
    if key == "all":
        key = None
    mode = install_mode.strip().lower()
    if mode not in {"link", "copy"}:
        mode = "link"
    result = skill_manager.install_all(key, install_mode=mode)
    action = "挂靠" if mode == "link" else "复制"
    message = f"已{action} {result.installed} 个技能"
    if result.skipped:
        message += f"，跳过 {result.skipped} 个已挂靠"
    if result.failed:
        message += f"，{len(result.failed)} 个失败"
    return SkillInstallAllResponse(
        installed=result.installed,
        skipped=result.skipped,
        failed=result.failed[:20],
        message=message,
    )


@app.post("/api/skills/install")
def install_skill(request: Request, body: SkillInstallRequest) -> SkillRecordResponse:
    skill_manager: SkillManager = _svc(request).skill_manager
    mode = body.install_mode.strip().lower()
    if mode not in {"link", "copy"}:
        mode = "link"
    try:
        record = skill_manager.install(
            body.source_path,
            target_name=body.target_name.strip() or None,
            install_mode=mode,
        )
    except AgentError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return SkillRecordResponse(
        name=record.name,
        description=record.description,
        path=record.path,
        source_key=record.source_key,
        source_label=record.source_label,
        source_root=record.source_root,
        origin_path=record.origin_path,
        install_mode=record.install_mode,
        link_target=record.link_target,
        status=record.status,
        category=record.category,
        tags=list(record.tags),
        installed=record.installed,
    )


@app.post("/api/skills/uninstall")
def uninstall_skill(request: Request, body: SkillUninstallRequest) -> dict[str, str]:
    skill_manager: SkillManager = _svc(request).skill_manager
    try:
        skill_manager.uninstall(body.name.strip())
    except AgentError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"status": "ok", "name": body.name.strip()}


@app.put("/api/skills/{name}/category")
def update_skill_category(name: str, request: Request, body: SkillCategoryUpdateRequest) -> dict[str, object]:
    skill_manager: SkillManager = _svc(request).skill_manager
    skill_manager.update_category(name, body.category, body.tags)
    return {"status": "ok", "name": name, "category": body.category, "tags": body.tags}


@app.get("/api/skills/installed/{name}")
def read_installed_skill(name: str, request: Request) -> dict[str, str]:
    skill_manager: SkillManager = _svc(request).skill_manager
    try:
        body = skill_manager.read_skill_body(name, max_chars=12000)
    except AgentError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"name": name, "markdown": body}


@app.get("/api/kb/tree")
def kb_tree(request: Request) -> dict[str, object]:
    workspace: KnowledgeWorkspace = _svc(request).workspace
    return {"topics": workspace.topic_tree()}


@app.get("/api/kb/notes")
def kb_notes(request: Request) -> NoteListResponse:
    workspace: KnowledgeWorkspace = _svc(request).workspace
    notes = workspace.list_notes()
    return NoteListResponse(
        notes=[
            {
                "chunk_id": note.chunk_id,
                "path": note.path,
                "title": note.title,
                "topic": note.topic,
                "source": note.source,
                "updated_at": note.updated_at,
            }
            for note in notes
        ]
    )


@app.get("/api/kb/note")
def kb_note(path: str, request: Request) -> NoteDetailResponse:
    workspace: KnowledgeWorkspace = _svc(request).workspace
    try:
        content = workspace.read_note(path)
    except IngestError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return NoteDetailResponse(path=path, content=content)


@app.put("/api/kb/note")
def kb_note_update(body: NoteUpdateRequest, request: Request) -> NoteDetailResponse:
    workspace: KnowledgeWorkspace = _svc(request).workspace
    try:
        workspace.write_note(body.path, body.content)
    except IngestError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return NoteDetailResponse(path=body.path, content=body.content)


@app.get("/api/briefing/latest")
def briefing_latest() -> BriefingResponse:
    payload = BackgroundScheduler.load_latest_briefing(settings.resolved_data_dir())
    if payload is None:
        raise HTTPException(status_code=404, detail="暂无早报")
    return BriefingResponse(
        markdown=payload["markdown"],
        generated_at=payload["generated_at"],
    )


@app.get("/api/graph")
def graph_data(filter: str = "all", request: Request = None) -> GraphResponse:
    workspace: KnowledgeWorkspace = _svc(request).workspace
    store: MemoryStore = _svc(request).store
    graph = GraphBuilder(workspace, store).build(filter_mode=filter)
    return GraphResponse(
        nodes=[
            {
                "id": node.id,
                "name": node.name,
                "type": node.node_type,
                **node.meta,
            }
            for node in graph.nodes
        ],
        edges=[
            {"source": edge.source, "target": edge.target, "relation": edge.relation}
            for edge in graph.edges
        ],
        layout=graph.layout,
    )


@app.post("/api/kb/rebuild")
async def kb_rebuild(request: Request) -> dict[str, int]:
    sync_service: SyncService = _svc(request).sync_service
    count = await asyncio.to_thread(sync_service.export_kb_from_memory)
    return {"exported": count}


def _platform_field_values(source: SourceKind, request: Request) -> dict[str, object]:
    platform_store: PlatformConfigStore = _svc(request).platform_store
    section = platform_store.get_section(source)
    if source is SourceKind.EMAIL:
        return mask_secrets(section)
    return section


def _build_platform_cards(request: Request) -> list[PlatformCardResponse]:
    sync_service: SyncService = _svc(request).sync_service
    stored_map = {item.source: item for item in sync_service.get_stored_health()}
    cards: list[PlatformCardResponse] = []
    for definition in PLATFORM_DEFINITIONS:
        health = stored_map.get(definition.source)
        status = health.status.value if health else "not_configured"
        raw_message = health.message if health else "未检测"
        message = format_connector_message(raw_message)
        fields: list[PlatformFieldResponse] = []
        values = _platform_field_values(definition.source, request)
        for field in definition.fields:
            raw_value = values.get(field.key, "")
            if field.field_type == "number":
                display_value: str | int | bool = int(raw_value or 1000)
            elif field.field_type == "checkbox":
                display_value = bool(raw_value)
            else:
                display_value = str(raw_value or "")
            fields.append(
                PlatformFieldResponse(
                    key=field.key,
                    label=field.label,
                    field_type=field.field_type,
                    placeholder=field.placeholder,
                    value=display_value,
                )
            )
        cards.append(
            PlatformCardResponse(
                source=definition.source.value,
                name=definition.name,
                description=definition.description,
                kind=definition.kind,
                setup_hint=definition.setup_hint,
                status=status,
                status_message=message,
                fields=fields,
            )
        )
    return cards


@app.get("/api/settings/platforms")
def list_platform_settings(request: Request) -> list[PlatformCardResponse]:
    platform_store: PlatformConfigStore = _svc(request).platform_store
    sync_service: SyncService = _svc(request).sync_service
    settings.load_platform_config(platform_store)
    sync_service.reload_connectors()
    return _build_platform_cards(request)


@app.put("/api/settings/platforms/{source}")
def update_platform_settings(
    source: SourceKind,
    request: Request,
    body: PlatformUpdateRequest,
) -> PlatformCardResponse:
    platform_store: PlatformConfigStore = _svc(request).platform_store
    sync_service: SyncService = _svc(request).sync_service
    platform_store.update_section(source, body.values)
    settings.load_platform_config(platform_store)
    sync_service.reload_connectors()
    for card in _build_platform_cards(request):
        if card.source == source.value:
            return card
    raise HTTPException(status_code=404, detail=f"unknown platform card: {source.value}")


@app.post("/api/settings/platforms/{source}/test")
async def test_platform_settings(source: SourceKind, request: Request) -> dict[str, str]:
    platform_store: PlatformConfigStore = _svc(request).platform_store
    sync_service: SyncService = _svc(request).sync_service
    settings.load_platform_config(platform_store)
    sync_service.reload_connectors()
    result = await asyncio.to_thread(sync_service.sync_source, source)
    return {
        "source": result.source.value,
        "status": result.health.status.value,
        "message": result.health.message,
        "inserted": str(result.inserted),
    }


if DESKTOP_UI_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DESKTOP_UI_DIR), name="assets")

    _NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}

    @app.get("/")
    def desktop_ui() -> FileResponse:
        return FileResponse(DESKTOP_UI_DIR / "index.html", headers=_NO_CACHE)

    @app.get("/workspace")
    def workspace_ui() -> FileResponse:
        return FileResponse(DESKTOP_UI_DIR / "workspace.html", headers=_NO_CACHE)

    @app.get("/mascot")
    def mascot_ui() -> FileResponse:
        return FileResponse(DESKTOP_UI_DIR / "mascot.html", headers=_NO_CACHE)
