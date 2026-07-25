"""Shared FastAPI request/response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
    chat_facts_markdown: str = ""
    is_user_edited: bool
    sections: list[dict[str, str | int]]


class ProfileUpdateRequest(BaseModel):
    markdown: str = Field(max_length=100_000)


class MemorySearchResponse(BaseModel):
    query: str
    results: list[dict[str, str]]


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=8000)
    trace_id: str = Field(default="", max_length=64)
    thread_id: str = Field(default="", max_length=64)
    parent_message_id: str = Field(default="", max_length=64)
    working_dir: str = Field(default="", max_length=1024)
    attachments: list[str] = Field(default_factory=list, max_length=10)


class ChatCancelRequest(BaseModel):
    trace_id: str = Field(min_length=1, max_length=64)


class ChatUploadsFromPathsRequest(BaseModel):
    thread_id: str = Field(default="", max_length=64)
    paths: list[str] = Field(default_factory=list, max_length=10)


class ChatThreadActiveLeafRequest(BaseModel):
    leaf_id: str = Field(min_length=1, max_length=64)


class ChatThreadRollbackRequest(BaseModel):
    to_message_id: str = Field(min_length=1, max_length=64)


class ChatThreadRestoreRequest(BaseModel):
    message_id: str = Field(min_length=1, max_length=64)


class ChatThreadsPutRequest(BaseModel):
    current_id: str = Field(default="", max_length=64)
    threads: list[dict[str, object]] = Field(default_factory=list)


class ChatThreadCreateRequest(BaseModel):
    title: str = Field(default="新对话", max_length=120)


class ChatThreadCurrentRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=64)


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
    confirmation_diff: str = ""
    allow_permanent_read: bool = False
    allow_session_write: bool = False
    grounding_verified: bool = True
    grounding_note: str = ""
    files_read: list[str] = []
    usage_prompt_tokens: int = 0
    usage_completion_tokens: int = 0
    usage_total_tokens: int = 0
    confirmation_scope: str = ""
    raw_reply: str = ""


class ConfirmActionRequest(BaseModel):
    action_id: str = Field(min_length=1)
    approved: bool
    grant_permanent_read: bool = False
    grant_session_write: bool = False
    trace_id: str = Field(default="", max_length=64)
    thread_id: str = Field(default="", max_length=64)


class BriefingResponse(BaseModel):
    markdown: str
    generated_at: str


class McpServerUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=48)
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    transport: str = "stdio"
    headers: dict[str, str] = Field(default_factory=dict)
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
    mcp_provider: bool = False


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


class HarnessConfigSchema(BaseModel):
    max_tool_rounds: int = Field(default=20, ge=1, le=64)
    light_max_steps: int = Field(default=3, ge=1, le=16)
    compaction_max_tokens: int = Field(default=24_000, ge=4_000, le=128_000)
    compaction_keep_tail: int = Field(default=8, ge=2, le=64)
    trace_retention: str = Field(default="full", pattern="^(full|summary|off)$")
    trace_retain_days: int = Field(default=30, ge=0, le=365)
    max_tool_output_chars: int = Field(default=12_000, ge=500, le=100_000)


class AgentConfigResponse(BaseModel):
    provider: str
    api_key_masked: str
    base_url: str
    model: str
    temperature: float
    max_history_turns: int
    response_style: str
    agent_profile: str = "auto"
    shell_working_dir: str = ""
    status: str
    status_message: str
    active_source: str
    providers: list[dict[str, str]]
    harness: HarnessConfigSchema = Field(default_factory=HarnessConfigSchema)


class AgentConfigUpdateRequest(BaseModel):
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    temperature: float | None = None
    max_history_turns: int | None = None
    response_style: str = ""
    agent_profile: str = ""
    shell_working_dir: str | None = None
    harness: HarnessConfigSchema | None = None


class McpQuickstartFilesystemRequest(BaseModel):
    root: str = ""


class AgentTestResponse(BaseModel):
    status: str
    message: str
    model: str
    source: str


class ShibeiConfigResponse(BaseModel):
    enabled: bool
    sources: list[str]
    extensions: list[str]
    search_engine: str
    auto_import_on_sync: bool
    collection: str
    install_path: str
    config_path: str
    db_path: str
    status: str
    status_message: str
    source_count: int
    shibei_available: bool


class ShibeiConfigUpdateRequest(BaseModel):
    enabled: bool | None = None
    install_path: str | None = None
    config_path: str | None = None
    auto_import_on_sync: bool | None = None


class ShibeiActionResponse(BaseModel):
    status: str
    message: str


class ShibeiSearchRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=50)
    tag: str | None = None


class ShibeiSourceReadResponse(BaseModel):
    path: str
    name: str
    content: str


class WebSearchResponse(BaseModel):
    query: str
    engine: str
    results: list[dict[str, str]]


