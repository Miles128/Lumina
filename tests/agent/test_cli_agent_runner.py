"""Tests for CLI agent runner (FR-30)."""

from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock

import pytest

from secretary.agent.cli_agent.runner import CliAgentRunner
from secretary.services.cli_agent_config import CliAgentConfigStore, CliProviderConfig


@pytest.fixture
def cli_store(tmp_path):
    store = CliAgentConfigStore(tmp_path / "cli-agents.json")
    store.upsert_provider(
        "mock",
        CliProviderConfig(
            command="echo",
            args=["ok"],
            prompt_mode="argv_tail",
            timeout=30,
            enabled=True,
            available_check="echo",
        ),
    )
    return store


def _install_subprocess_success(monkeypatch, *, stdout: str = "tests passed") -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    if os.name == "posix":
        class _Proc:
            returncode = 0
            pid = 4242

            def communicate(self, input=None, timeout=None):
                return stdout, ""

            def poll(self):
                return 0

        monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: _Proc())
        monkeypatch.setattr("os.setsid", lambda: None)
        return

    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: MagicMock(returncode=0, stdout=stdout, stderr=""),
    )


def test_cli_runner_success(cli_store, tmp_path, monkeypatch) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _install_subprocess_success(monkeypatch)
    runner = CliAgentRunner(cli_store, projects_dir=root)
    output = runner.run_from_tool(
        {"provider": "mock", "goal": "run pytest"},
        root,
    )
    assert "tests passed" in output
    assert "成功" in output


def test_cli_runner_rejects_cwd_outside_allowed(cli_store, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    runner = CliAgentRunner(cli_store, projects_dir=tmp_path / "projects")
    output = runner.run_from_tool(
        {"provider": "mock", "goal": "x", "cwd": "/tmp/outside"},
        tmp_path,
    )
    assert output.startswith("Error:")


def test_cli_runner_emits_progress(cli_store, tmp_path, monkeypatch) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _install_subprocess_success(monkeypatch, stdout="done")
    events = []
    runner = CliAgentRunner(cli_store, projects_dir=root)
    runner.run_from_tool(
        {"provider": "mock", "goal": "task"},
        root,
        progress_callback=events.append,
    )
    kinds = [event.kind for event in events]
    assert kinds == ["cli_agent_started", "cli_agent_finished"]


def test_cli_runner_timeout(cli_store, tmp_path, monkeypatch) -> None:
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    if os.name == "posix":
        class _Proc:
            pid = 4242

            def communicate(self, input=None, timeout=None):
                raise subprocess.TimeoutExpired(cmd="echo", timeout=1)

            def poll(self):
                return None

        monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: _Proc())
        monkeypatch.setattr("os.setsid", lambda: None)
        monkeypatch.setattr("os.getpgid", lambda pid: pid)
        monkeypatch.setattr("os.killpg", lambda pgid, sig: None)
    else:
        def raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="echo", timeout=1)

        monkeypatch.setattr("subprocess.run", raise_timeout)

    runner = CliAgentRunner(cli_store, projects_dir=root)
    output = runner.run_from_tool({"provider": "mock", "goal": "slow"}, root)
    assert "timed out" in output.lower() or "超时" in output
