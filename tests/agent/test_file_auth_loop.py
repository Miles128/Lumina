"""Tests for file-access confirmation in the agent loop."""

from pathlib import Path

from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import AgentLoop, FileWriteTool, ListDirTool, ShellTool
from secretary.services.file_auth import FileAuthService


def _llm_config() -> LlmConfig:
    return LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )


def test_read_never_requires_confirmation(tmp_path: Path) -> None:
    auth = FileAuthService(tmp_path / "file_auth.json")
    loop = AgentLoop(_llm_config(), tools=[ListDirTool()], file_auth=auth)
    needs_confirm, kind = loop._requires_confirmation(
        loop._tools["list_dir"],
        {"path": str(tmp_path)},
    )
    assert needs_confirm is False
    assert kind == ""


def test_file_read_never_requires_confirmation(tmp_path: Path) -> None:
    from secretary.agent.tools.fs import FileReadTool

    auth = FileAuthService(tmp_path / "file_auth.json")
    sample = tmp_path / "note.txt"
    sample.write_text("hello", encoding="utf-8")
    loop = AgentLoop(_llm_config(), tools=[FileReadTool()], file_auth=auth)
    needs_confirm, kind = loop._requires_confirmation(
        loop._tools["file_read"],
        {"path": str(sample)},
    )
    assert needs_confirm is False
    assert kind == ""


def test_search_files_never_requires_confirmation(tmp_path: Path) -> None:
    from secretary.agent.p0_tools import SearchFilesTool

    auth = FileAuthService(tmp_path / "file_auth.json")
    loop = AgentLoop(_llm_config(), tools=[SearchFilesTool()], file_auth=auth)
    needs_confirm, kind = loop._requires_confirmation(
        loop._tools["search_files"],
        {"pattern": "*.py", "path": str(tmp_path)},
    )
    assert needs_confirm is False
    assert kind == ""


def test_mkdir_shell_requires_confirmation(tmp_path: Path) -> None:
    auth = FileAuthService(tmp_path / "file_auth.json")
    loop = AgentLoop(_llm_config(), tools=[ShellTool()], file_auth=auth)
    needs_confirm, kind = loop._requires_confirmation(
        loop._tools["shell"],
        {"command": f"mkdir -p {tmp_path / 'newdir'}"},
    )
    assert needs_confirm is True
    assert kind == "shell"


def test_write_new_requires_confirmation_without_session_grant(tmp_path: Path) -> None:
    auth = FileAuthService(tmp_path / "file_auth.json")
    loop = AgentLoop(_llm_config(), tools=[FileWriteTool()], file_auth=auth)
    target = tmp_path / "new.txt"
    needs_confirm, kind = loop._requires_confirmation(
        loop._tools["file_write"],
        {"path": str(target), "content": "hello"},
    )
    assert needs_confirm is True
    assert kind == "write_new"


def test_write_modify_always_requires_confirmation(tmp_path: Path) -> None:
    auth = FileAuthService(tmp_path / "file_auth.json")
    auth.grant_session_write_new()
    existing = tmp_path / "existing.txt"
    existing.write_text("old", encoding="utf-8")
    loop = AgentLoop(_llm_config(), tools=[FileWriteTool()], file_auth=auth)
    needs_confirm, kind = loop._requires_confirmation(
        loop._tools["file_write"],
        {"path": str(existing), "content": "new"},
    )
    assert needs_confirm is True
    assert kind == "write_modify"


def test_read_only_shell_command_does_not_require_confirmation(tmp_path: Path) -> None:
    auth = FileAuthService(tmp_path / "file_auth.json")
    loop = AgentLoop(_llm_config(), tools=[ShellTool()], file_auth=auth)
    needs_confirm, kind = loop._requires_confirmation(
        loop._tools["shell"],
        {"command": "find /Users -maxdepth 3 -type f 2>/dev/null | head -10"},
    )
    assert needs_confirm is False
    assert kind == ""


def test_mdfind_shell_command_does_not_require_confirmation(tmp_path: Path) -> None:
    auth = FileAuthService(tmp_path / "file_auth.json")
    loop = AgentLoop(_llm_config(), tools=[ShellTool()], file_auth=auth)
    needs_confirm, kind = loop._requires_confirmation(
        loop._tools["shell"],
        {"command": 'mdfind "kMDItemFSName == *.md" | head -5'},
    )
    assert needs_confirm is False
    assert kind == ""


def test_write_like_shell_command_still_requires_confirmation(tmp_path: Path) -> None:
    auth = FileAuthService(tmp_path / "file_auth.json")
    loop = AgentLoop(_llm_config(), tools=[ShellTool()], file_auth=auth)
    needs_confirm, kind = loop._requires_confirmation(
        loop._tools["shell"],
        {"command": "echo hi > /tmp/demo.txt"},
    )
    assert needs_confirm is True
    assert kind == "shell"
