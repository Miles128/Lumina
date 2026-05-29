"""Tests for profile summarizer."""

from pathlib import Path
from unittest.mock import patch

from secretary.agent.llm_config import LlmConfig
from secretary.config import Settings
from secretary.core.types import MemoryChunk, SourceKind
from secretary.memory.db import MemoryStore
from secretary.services.profile_summarizer import build_profile


def test_build_profile_falls_back_without_llm(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    store.upsert_chunks(
        [
            MemoryChunk(
                chunk_id="1",
                source=SourceKind.WEREAD,
                title="微信读书 · 测试书",
                content="内容",
                metadata={},
            )
        ]
    )
    profile = build_profile(store, None, None)
    assert "测试书" in profile.markdown


def test_build_profile_uses_llm_when_available(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    store.upsert_chunks(
        [
            MemoryChunk(
                chunk_id="1",
                source=SourceKind.WEREAD,
                title="微信读书 · 测试书",
                content="内容",
                metadata={},
            )
        ]
    )
    config = LlmConfig(
        api_key="k",
        base_url="https://example.com/v1",
        model="m",
        source="env",
    )
    with patch(
        "secretary.services.profile_summarizer.chat_completion",
        return_value="## 阅读偏好\n喜欢深度阅读。",
    ):
        profile = build_profile(store, None, config)
    assert "深度阅读" in profile.markdown
