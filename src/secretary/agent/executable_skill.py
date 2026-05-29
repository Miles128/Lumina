"""Executable skill system: from prompt-only to runnable modules.

Supports two skill types:
1. PromptSkill: traditional SKILL.md (backward compatible)
2. ExecutableSkill: manifest.json + run.py (can execute code)
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from secretary.exceptions import AgentError

MANIFEST_FILE = "manifest.json"
RUN_FILE = "run.py"
SKILL_MD_FILE = "SKILL.md"

_SAFE_IMPORTS = frozenset({
    "json", "os", "pathlib", "datetime", "re", "math",
    "collections", "itertools", "functools", "typing",
    "urllib.parse", "urllib.request", "csv", "io",
    "textwrap", "hashlib", "base64", "string", "random",
})


@dataclass(frozen=True)
class SkillManifest:
    name: str
    version: str = "1.0.0"
    description: str = ""
    tools: tuple[str, ...] = ()
    parameters: tuple[str, ...] = ()
    timeout: int = 30

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillManifest:
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            tools=tuple(data.get("tools", [])),
            parameters=tuple(data.get("parameters", [])),
            timeout=min(data.get("timeout", 30), 120),
        )


@dataclass
class SkillExecutionResult:
    success: bool
    output: str
    error: str | None = None
    exit_code: int = 0


class ExecutableSkill:
    def __init__(self, skill_dir: Path) -> None:
        self._dir = skill_dir
        self._manifest: SkillManifest | None = None
        self._run_code: str | None = None

    @property
    def manifest(self) -> SkillManifest:
        if self._manifest is None:
            self._load()
        assert self._manifest is not None
        return self._manifest

    @property
    def is_executable(self) -> bool:
        return (self._dir / RUN_FILE).exists() and (self._dir / MANIFEST_FILE).exists()

    def _load(self) -> None:
        manifest_path = self._dir / MANIFEST_FILE
        if manifest_path.exists():
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self._manifest = SkillManifest.from_dict(data)
        else:
            self._manifest = SkillManifest(name=self._dir.name)

        run_path = self._dir / RUN_FILE
        if run_path.exists():
            self._run_code = run_path.read_text(encoding="utf-8")

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> SkillExecutionResult:
        if self._run_code is None:
            return SkillExecutionResult(success=False, output="", error="No run.py found")

        timeout = self.manifest.timeout
        for key in self.manifest.parameters:
            if key not in arguments:
                arguments[key] = ""

        args_json = json.dumps(arguments, ensure_ascii=False)

        wrapper = (
            "import sys, json;\n"
            "args = json.loads(sys.argv[1]);\n"
            f"_code = {repr(self._run_code)};\n"
            "exec(_code, {'__builtins__': __builtins__, 'args': args, 'json': json, 'print': print})\n"
        )

        try:
            result = subprocess.run(
                ["python3", "-c", wrapper, args_json],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(working_dir),
            )
            output = result.stdout.strip()
            error = result.stderr.strip() if result.stderr else None
            if result.returncode != 0 and not output:
                return SkillExecutionResult(
                    success=False,
                    output=output or "(no output)",
                    error=error,
                    exit_code=result.returncode,
                )
            return SkillExecutionResult(
                success=result.returncode == 0,
                output=output or "(no output)",
                error=error,
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return SkillExecutionResult(
                success=False, output="", error=f"Timeout after {timeout}s"
            )
        except Exception as exc:
            return SkillExecutionResult(success=False, output="", error=str(exc))

    def prompt_block(self) -> str:
        if self.is_executable:
            tools = ", ".join(self.manifest.tools) if self.manifest.tools else "none"
            params = ", ".join(self.manifest.parameters) if self.manifest.parameters else "none"
            return (
                f"### Skill: {self.manifest.name}\n"
                f"{self.manifest.description}\n"
                f"Type: executable | Tools: {tools} | Parameters: {params}"
            )
        skill_md = self._dir / SKILL_MD_FILE
        if skill_md.exists():
            text = skill_md.read_text(encoding="utf-8", errors="replace")
            import re
            fm = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
            body = fm.sub("", text).strip()
            return f"### Skill: {self.manifest.name}\n{body[:900]}"
        return f"### Skill: {self.manifest.name}\n{self.manifest.description}"


class ExecutableSkillManager:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._skills_dir = data_dir / "skills"

    @property
    def skills_dir(self) -> Path:
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        return self._skills_dir

    def list_skills(self) -> list[ExecutableSkill]:
        skills: list[ExecutableSkill] = []
        if not self._skills_dir.exists():
            return skills
        for folder in sorted(self._skills_dir.iterdir()):
            if not folder.is_dir():
                continue
            if (folder / SKILL_MD_FILE).exists() or (folder / MANIFEST_FILE).exists():
                skills.append(ExecutableSkill(folder))
        return skills

    def get_skill(self, name: str) -> ExecutableSkill | None:
        direct = self._skills_dir / name
        if direct.is_dir():
            return ExecutableSkill(direct)
        for folder in self._skills_dir.iterdir():
            if not folder.is_dir():
                continue
            skill = ExecutableSkill(folder)
            if skill.manifest.name == name:
                return skill
        return None

    def execute_skill(
        self, name: str, arguments: dict[str, Any], working_dir: Path | None = None
    ) -> SkillExecutionResult:
        skill = self.get_skill(name)
        if skill is None:
            raise AgentError(f"Skill not found: {name}")
        if not skill.is_executable:
            raise AgentError(f"Skill '{name}' is prompt-only, not executable")
        return skill.execute(arguments, working_dir or Path.cwd())

    def prompt_block(self, max_skills: int = 8) -> str:
        skills = self.list_skills()
        if not skills:
            return "No skills installed."
        lines = ["Installed skills (use tool-call to invoke executable ones):"]
        for skill in skills[:max_skills]:
            lines.append(skill.prompt_block())
        return "\n\n".join(lines)

    def create_executable_skill(
        self,
        name: str,
        description: str,
        run_code: str,
        tools: list[str] | None = None,
        parameters: list[str] | None = None,
        timeout: int = 30,
    ) -> Path:
        safe_name = _safe_folder_name(name)
        skill_dir = self.skills_dir / safe_name
        if skill_dir.exists():
            raise AgentError(f"Skill already exists: {safe_name}")
        skill_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "name": name,
            "version": "1.0.0",
            "description": description,
            "tools": tools or [],
            "parameters": parameters or [],
            "timeout": min(timeout, 120),
        }
        (skill_dir / MANIFEST_FILE).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (skill_dir / RUN_FILE).write_text(run_code, encoding="utf-8")
        return skill_dir


def _safe_folder_name(name: str) -> str:
    import re
    cleaned = re.sub(r"[^\w\-.]+", "-", name.strip()).strip("-")
    return cleaned or "skill"
