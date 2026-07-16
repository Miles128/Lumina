"""Tests for durable memory compression."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from secretary.agent.llm_config import LlmConfig
from secretary.memory.lumina_memory import LuminaMemory
from secretary.services.memory_compress import MemoryCompressionService


def test_compress_skips_when_under_threshold(tmp_path: Path) -> None:
    memory = LuminaMemory(tmp_path)
    memory.write_memory_md("短记忆")
    service = MemoryCompressionService(memory)
    config = LlmConfig(
        api_key="k",
        base_url="https://example.com/v1",
        model="m",
        source="test",
    )
    assert service.compress_if_needed(config) is False


def test_compress_rewrites_when_over_threshold(tmp_path: Path) -> None:
    memory = LuminaMemory(tmp_path)
    long_text = "稳定事实。" * 400
    memory.write_memory_md(long_text)
    service = MemoryCompressionService(memory)
    config = LlmConfig(
        api_key="k",
        base_url="https://example.com/v1",
        model="m",
        source="test",
    )
    with patch(
        "secretary.services.memory_compress.chat_completion",
        return_value="压缩后记忆",
    ):
        assert service.compress_if_needed(config) is True
    assert memory.read_memory_md() == "压缩后记忆"


def test_compress_if_needed_skips_user_md() -> None:
    """compress_if_needed 只压缩 MEMORY.md，不再读 USER.md。"""
    memory = MagicMock()
    memory.read_memory_md.return_value = ""
    # 即便 mock 上有 read_user_md 属性，也不应被调用
    memory.read_user_md = MagicMock()
    svc = MemoryCompressionService(memory)
    config = LlmConfig(
        api_key="k",
        base_url="https://example.com/v1",
        model="m",
        source="test",
    )

    changed = svc.compress_if_needed(config)

    assert changed is False
    memory.read_memory_md.assert_called_once()
    memory.read_user_md.assert_not_called()
