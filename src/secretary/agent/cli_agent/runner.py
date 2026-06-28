"""Run external CLI agents as subprocesses; return truncated summary only."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from secretary.agent.progress_events import ProgressEvent
from secretary.services.cli_agent_config import CliAgentConfigStore, CliProviderConfig

logger = logging.getLogger(__name__)


class CliAgentRunner:
    def __init__(
        self,
        config_store: CliAgentConfigStore,
        *,
        projects_dir: Path | None = None,
        audit_dir: Path | None = None,
    ) -> None:
        self._config_store = config_store
        self._projects_dir = projects_dir.expanduser().resolve() if projects_dir else None
        self._audit_dir = audit_dir

    def run_from_tool(
        self,
        arguments: dict[str, Any],
        default_cwd: Path,
        *,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> str:
        provider = str(arguments.get("provider", "")).strip()
        goal = str(arguments.get("goal", "")).strip()
        context = str(arguments.get("context", "")).strip()
        cwd_raw = str(arguments.get("cwd", "")).strip()
        timeout_raw = arguments.get("timeout")

        if not provider:
            document = self._config_store.load()
            provider = document.defaults.provider.strip() or "codex"
        if not goal:
            return "Error: spawn_cli_agent requires a non-empty goal."

        if not self._config_store.is_enabled():
            return "Error: 外接 CLI Agent 未启用。请在设置 → CLI Agents 中开启，或继续使用灵犀自有 Agent。"

        cfg = self._config_store.get_provider(provider)
        if cfg is None:
            known = ", ".join(sorted(self._config_store.load().providers))
            return f"Error: unknown or disabled CLI provider '{provider}'. Known: {known}"

        check_name = (cfg.available_check or cfg.command).strip()
        if check_name and shutil.which(check_name) is None:
            return f"Error: CLI '{check_name}' 未安装或不在 PATH 中。"

        cwd = default_cwd
        if cwd_raw:
            cwd = Path(cwd_raw).expanduser()
        cwd_error = self._validate_cwd(cwd)
        if cwd_error:
            return cwd_error

        timeout = cfg.timeout
        if timeout_raw is not None:
            try:
                timeout = min(int(timeout_raw), cfg.timeout)
            except (TypeError, ValueError):
                pass

        prompt = self._build_prompt(goal, context)
        self._emit(
            progress_callback,
            ProgressEvent(
                kind="cli_agent_started",
                iteration=0,
                tool_name="spawn_cli_agent",
                archetype=provider,
                goal=goal[:240],
                detail=f"cwd: {cwd}",
            ),
        )
        try:
            exit_code, stdout, stderr = self._run_subprocess(cfg, prompt, cwd, timeout)
        except subprocess.TimeoutExpired:
            self._emit(
                progress_callback,
                ProgressEvent(
                    kind="cli_agent_finished",
                    iteration=0,
                    tool_name="spawn_cli_agent",
                    archetype=provider,
                    success=False,
                    message=f"超时（{timeout}s）",
                ),
            )
            return f"Error: CLI agent '{provider}' timed out after {timeout}s"

        summary = self._summarize(cfg, stdout, stderr)
        self._write_audit(provider, goal, cwd, exit_code, stdout, stderr)
        success = exit_code == 0
        self._emit(
            progress_callback,
            ProgressEvent(
                kind="cli_agent_finished",
                iteration=0,
                tool_name="spawn_cli_agent",
                archetype=provider,
                success=success,
                message=summary[:240],
                detail=f"exit={exit_code}",
            ),
        )
        status = "成功" if success else f"失败 (exit {exit_code})"
        return f"[CLI {provider} · {status}]\n\n{summary}"

    def _validate_cwd(self, cwd: Path) -> str | None:
        try:
            resolved = cwd.expanduser().resolve()
        except OSError as exc:
            return f"Error: invalid cwd: {exc}"
        if not resolved.is_dir():
            return f"Error: cwd 不存在: {resolved}"
        home = Path.home().resolve()
        allowed_roots = [home]
        if self._projects_dir is not None and self._projects_dir.is_dir():
            allowed_roots.append(self._projects_dir.resolve())
        for root in allowed_roots:
            try:
                resolved.relative_to(root)
                return None
            except ValueError:
                continue
        return f"Error: cwd 必须在 home 或 projects 目录下: {resolved}"

    @staticmethod
    def _build_prompt(goal: str, context: str) -> str:
        if context.strip():
            return f"{goal.strip()}\n\n---\nContext:\n{context.strip()}"
        return goal.strip()

    def _run_subprocess(
        self,
        cfg: CliProviderConfig,
        prompt: str,
        cwd: Path,
        timeout: int,
    ) -> tuple[int, str, str]:
        env = os.environ.copy()
        env.update(cfg.env)
        argv = [cfg.command, *cfg.args]
        stdin_text: str | None = None
        if cfg.prompt_mode == "stdin":
            stdin_text = prompt
        elif cfg.prompt_flag:
            argv = self._insert_prompt_after_flag(argv, prompt, cfg.prompt_flag)
        else:
            argv = [*argv, prompt]

        if os.name == "posix":
            proc = subprocess.Popen(
                argv,
                cwd=str(cwd),
                env=env,
                stdin=subprocess.PIPE if stdin_text else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=os.setsid,
            )
            try:
                stdout, stderr = proc.communicate(input=stdin_text, timeout=timeout)
            except subprocess.TimeoutExpired:
                self._kill_process_group(proc)
                raise
            return proc.returncode or 0, stdout or "", stderr or ""

        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return completed.returncode, completed.stdout or "", completed.stderr or ""

    @staticmethod
    def _insert_prompt_after_flag(argv: list[str], prompt: str, flag: str) -> list[str]:
        for index, arg in enumerate(argv):
            if arg == flag:
                return [*argv[: index + 1], prompt, *argv[index + 1 :]]
        return [*argv, flag, prompt]

    @staticmethod
    def _kill_process_group(proc: subprocess.Popen[str]) -> None:
        if proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception as exc:
            logger.warning("CLI process group kill failed: %s", exc)
            proc.kill()

    @staticmethod
    def _summarize(cfg: CliProviderConfig, stdout: str, stderr: str) -> str:
        stream = stderr if cfg.summary.from_stream == "stderr" else stdout
        if not stream.strip() and cfg.summary.from_stream == "stdout" and stderr.strip():
            stream = stderr
        text = stream.strip() or "(empty CLI output)"
        limit = cfg.summary.max_chars
        if len(text) > limit:
            return text[:limit] + "\n...[truncated]"
        return text

    def _write_audit(
        self,
        provider: str,
        goal: str,
        cwd: Path,
        exit_code: int,
        stdout: str,
        stderr: str,
    ) -> None:
        audit_root = self._audit_dir
        if audit_root is None:
            audit_root = self._config_store.path.parent / "logs" / "cli-agent"
        try:
            audit_root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            path = audit_root / f"{stamp}_{provider}.log"
            path.write_text(
                "\n".join(
                    [
                        f"provider={provider}",
                        f"cwd={cwd}",
                        f"exit_code={exit_code}",
                        f"goal={goal}",
                        "",
                        "=== stdout ===",
                        stdout,
                        "",
                        "=== stderr ===",
                        stderr,
                    ]
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.debug("CLI audit log skipped: %s", exc)

    @staticmethod
    def _emit(
        callback: Callable[[ProgressEvent], None] | None,
        event: ProgressEvent,
    ) -> None:
        if callback is None:
            return
        try:
            callback(event)
        except Exception as exc:
            logger.debug("CLI progress callback failed: %s", exc)
