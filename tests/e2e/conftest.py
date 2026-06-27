"""Shared fixtures for E2E tests (live backend + Playwright)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
E2E_PORT = os.environ.get("LUMINA_E2E_PORT", "8766")
E2E_HOST = os.environ.get("LUMINA_E2E_HOST", "127.0.0.1")


def _build_e2e_env(data_dir: Path) -> dict[str, str]:
    return {
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
        "LUMINA_DATA_DIR": str(data_dir),
        "SECRETARY_AUTO_SYNC_ENABLED": "false",
        "SECRETARY_BRIEFING_ENABLED": "false",
        "SECRETARY_THINK_ENABLED": "false",
        "SECRETARY_MEMORY_SUMMARY_ENABLED": "false",
        "PROMPT_GATE_ENABLED": "false",
        "MCP_AUTO_FILESYSTEM": "false",
        "SECRETARY_HOST": E2E_HOST,
        "SECRETARY_PORT": E2E_PORT,
        "NO_PROXY": "127.0.0.1,localhost,::1",
        "no_proxy": "127.0.0.1,localhost,::1",
    }


@pytest.fixture(scope="session")
def live_base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Start Lumina backend on 8766 for browser E2E (isolated data dir)."""
    data_dir = tmp_path_factory.mktemp("lumina_e2e_live")
    env = {**os.environ, **_build_e2e_env(data_dir)}
    log_path = data_dir / "backend.log"
    log_handle = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "secretary.main",
            "--host",
            E2E_HOST,
            "--port",
            E2E_PORT,
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    base = f"http://{E2E_HOST}:{E2E_PORT}"
    deadline = time.time() + 45
    last_error = "timeout"
    while time.time() < deadline:
        if proc.poll() is not None:
            log_handle.flush()
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-800:]
            raise RuntimeError(f"E2E backend exited early: {tail}")
        try:
            response = httpx.get(f"{base}/api/health", timeout=1.5, trust_env=False)
            if response.status_code == 200:
                break
        except Exception as error:
            last_error = str(error)
        time.sleep(0.25)
    else:
        proc.kill()
        log_handle.flush()
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-800:]
        raise RuntimeError(f"E2E backend failed to start: {last_error}\n{tail}")

    yield base

    proc.terminate()
    log_handle.close()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def browser_context_args(live_base_url: str) -> dict[str, object]:
    return {"base_url": live_base_url}
