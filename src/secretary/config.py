"""Application configuration."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from secretary.services.platform_config import PlatformConfigStore

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROJECT_ENV = _PROJECT_ROOT / ".env"
_ENV_FILE = _PROJECT_ENV if _PROJECT_ENV.exists() else Path(".env")


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    data_dir: Path = Field(default=Path.home() / ".lumina", alias="LUMINA_DATA_DIR")
    host: str = Field(default="127.0.0.1", alias="SECRETARY_HOST")
    port: int = Field(default=8765, alias="SECRETARY_PORT")
    sync_interval_minutes: int = Field(default=20, alias="SECRETARY_SYNC_INTERVAL_MINUTES")
    auto_sync_enabled: bool = Field(default=True, alias="SECRETARY_AUTO_SYNC_ENABLED")
    briefing_enabled: bool = Field(default=False, alias="SECRETARY_BRIEFING_ENABLED")
    briefing_hour: int = Field(default=8, alias="SECRETARY_BRIEFING_HOUR")
    think_enabled: bool = Field(default=False, alias="SECRETARY_THINK_ENABLED")
    think_interval_hours: int = Field(default=6, alias="SECRETARY_THINK_INTERVAL_HOURS")
    memory_summary_enabled: bool = Field(default=False, alias="SECRETARY_MEMORY_SUMMARY_ENABLED")
    memory_summary_hour: int = Field(default=23, alias="SECRETARY_MEMORY_SUMMARY_HOUR")

    email_imap_host: str = Field(default="", alias="EMAIL_IMAP_HOST")
    email_imap_port: int = Field(default=993, alias="EMAIL_IMAP_PORT")
    email_imap_user: str = Field(default="", alias="EMAIL_IMAP_USER")
    email_imap_password: str = Field(default="", alias="EMAIL_IMAP_PASSWORD")

    weixin_oa_urls: str = Field(default="", alias="WEIXIN_OA_URLS")
    cloud_drive_paths: str = Field(default="", alias="CLOUD_DRIVE_PATHS")
    local_documents_enabled: bool = Field(default=False, alias="LOCAL_DOCUMENTS_ENABLED")
    local_documents_path: str = Field(default="", alias="LOCAL_DOCUMENTS_PATH")
    local_documents_max_files: int = Field(default=25, alias="LOCAL_DOCUMENTS_MAX_FILES")

    projects_dir: str = Field(
        default=str(Path.home() / "Documents" / "My Projects"),
        alias="LUMINA_PROJECTS_DIR",
    )

    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_model: str = Field(default="", alias="LLM_MODEL")

    prompt_gate_enabled: bool = Field(
        default=False,
        alias="PROMPT_GATE_ENABLED",
        description="LLM input classifier before agent loop; default off (rules-only routing).",
    )
    prompt_gate_min_confidence: float = Field(default=0.6, alias="PROMPT_GATE_MIN_CONFIDENCE")
    web_intent_router_enabled: bool = Field(
        default=True,
        alias="WEB_INTENT_ROUTER_ENABLED",
        description=(
            "LLM web-search intent classifier as fallback when keyword routing misses "
            "(e.g. 'alva.ai 是什么'). Default on; set false to use keyword-only routing."
        ),
    )
    mcp_auto_filesystem: bool = Field(default=True, alias="MCP_AUTO_FILESYSTEM")

    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    brave_api_key: str = Field(default="", alias="BRAVE_API_KEY")
    bocha_api_key: str = Field(default="", alias="BOCHA_API_KEY")
    serper_api_key: str = Field(default="", alias="SERPER_API_KEY")
    serpapi_api_key: str = Field(default="", alias="SERPAPI_API_KEY")
    bing_search_api_key: str = Field(default="", alias="BING_SEARCH_API_KEY")
    perplexity_api_key: str = Field(default="", alias="PERPLEXITY_API_KEY")

    def resolved_data_dir(self) -> Path:
        expanded = self.data_dir.expanduser()
        expanded.mkdir(parents=True, exist_ok=True)
        return expanded

    def parsed_weixin_urls(self) -> list[str]:
        return [item.strip() for item in self.weixin_oa_urls.split(",") if item.strip()]

    def parsed_cloud_paths(self) -> list[Path]:
        return [
            Path(item.strip()).expanduser()
            for item in self.cloud_drive_paths.split(",")
            if item.strip()
        ]

    def load_platform_config(self, store: PlatformConfigStore) -> None:
        store.apply_to_settings(self)


settings = Settings()
_platform_store = PlatformConfigStore(settings.resolved_data_dir() / "platforms.json")
settings.load_platform_config(_platform_store)
