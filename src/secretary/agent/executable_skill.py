"""Executable skill system: from prompt-only to runnable modules.

Supports two skill types:
1. PromptSkill: traditional SKILL.md (backward compatible)
2. ExecutableSkill: manifest.json + run.py (can execute code)
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from secretary.exceptions import AgentError

MANIFEST_FILE = "manifest.json"
RUN_FILE = "run.py"
SKILL_MD_FILE = "SKILL.md"

_SAFE_IMPORTS = frozenset({
    "json", "os", "pathlib", "datetime", "re", "math",
    "collections", "itertools", "functools", "typing",
    "urllib.parse", "csv", "io",
    "textwrap", "hashlib", "base64", "string", "random",
    "time",
})

# Restricted builtins for skill sandbox. Dangerous utilities (exec, eval,
# compile, __import__) are removed or replaced with safe versions.
_SAFE_BUILTINS = frozenset({
    "True", "False", "None", "abs", "all", "any", "ascii", "bin", "bool",
    "bytearray", "bytes", "chr", "complex", "dict", "dir", "divmod",
    "enumerate", "filter", "float", "format", "frozenset", "hasattr",
    "hash", "hex", "id", "int", "isinstance", "issubclass",
    "iter", "len", "list", "map", "max", "memoryview", "min", "next",
    "object", "oct", "ord", "pow", "print", "property", "range", "repr",
    "reversed", "round", "set", "slice", "sorted", "str",
    "sum", "tuple", "type", "vars", "zip", "Exception", "OSError",
    "ValueError", "TypeError", "RuntimeError", "KeyError", "IndexError",
    "AttributeError", "LookupError", "ArithmeticError", "ZeroDivisionError",
    "FileNotFoundError", "PermissionError", "IsADirectoryError",
    "NotADirectoryError", "StopIteration", "BufferError",
})

_SANDBOX_PREAMBLE = '''\
import builtins as _builtins_module
import json
import os
import pathlib
import sys

_SAFE_IMPORTS = @@SAFE_IMPORTS@@
_SAFE_BUILTINS = @@SAFE_BUILTINS@@

_ARGS = json.loads(sys.argv[1])
_ALLOWED_ROOTS = [pathlib.Path(p).resolve() for p in sys.argv[2:]]


def _check_path(path, mode="write"):
    try:
        target = pathlib.Path(path).resolve()
    except Exception as exc:
        raise PermissionError(f"Sandbox blocked {mode}: invalid path {path!r}: {exc}")
    for root in _ALLOWED_ROOTS:
        try:
            target.relative_to(root)
            return
        except ValueError:
            continue
    raise PermissionError(f"Sandbox blocked {mode} outside allowed directories: {target}")


def _is_write_mode(mode):
    return isinstance(mode, str) and any(ch in mode for ch in "wax+")


_real_open = open


def _safe_open(file, mode="r", *args, **kwargs):
    if _is_write_mode(mode):
        _check_path(file, "write")
    return _real_open(file, mode, *args, **kwargs)


# Build a restricted os proxy: only safe, non-executing helpers exposed.
_real_os = os

# Neutralize truly dangerous os functions on the real module so that
# `import os` in user code cannot reach them either.
for _dangerous in (
    "system", "popen", "popen2", "popen3", "popen4",
    "execv", "execve", "execvp", "execvpe",
    "execl", "execle", "execlp", "execlpe",
    "spawnl", "spawnle", "spawnlp", "spawnlpe",
    "spawnv", "spawnve", "spawnvp", "spawnvpe",
    "fork", "forkpty",
    "chmod", "chown", "lchmod", "lchown", "fchmod", "fchown",
    "kill", "killpg",
    "setuid", "setgid", "seteuid", "setegid",
    "setreuid", "setregid", "setpgid", "setsid", "setpgrp",
    "ptrace", "startfile",
):
    if hasattr(_real_os, _dangerous):
        setattr(_real_os, _dangerous, None)


def _wrap_os_write(name):
    fn = getattr(_real_os, name)

    def _wrapped(path, *args, **kwargs):
        _check_path(path, "write")
        return fn(path, *args, **kwargs)

    return _wrapped


for _name in (
    "mkdir", "makedirs", "remove", "unlink", "rmdir", "removedirs",
    "rename", "replace", "link", "symlink", "mkfifo", "mknod",
):
    if hasattr(_real_os, _name):
        setattr(_real_os, _name, _wrap_os_write(_name))


class _SandboxOS:
    """Restricted os proxy: only safe helpers exposed."""


_os_proxy = _SandboxOS()
# Expose safe read-only functions and constants.
for _attr in (
    "getcwd", "listdir", "getpid", "cpu_count",
    "stat", "lstat", "walk", "scandir", "access",
    "sep", "linesep", "curdir", "pardir", "extsep", "pathsep", "name",
):
    if hasattr(_real_os, _attr):
        setattr(_os_proxy, _attr, getattr(_real_os, _attr))

# os.path submodule (all read-only: join, exists, basename, dirname, ...).
_os_proxy.path = _real_os.path

# Expose wrapped write helpers (path-checked) on the proxy as well.
for _name in (
    "mkdir", "makedirs", "remove", "unlink", "rmdir", "removedirs",
    "rename", "replace", "link", "symlink", "mkfifo", "mknod",
):
    if hasattr(_real_os, _name):
        setattr(_os_proxy, _name, getattr(_real_os, _name))


# Restrict __import__ to the allow-list defined by the parent process.
_real_import = __import__


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name not in _SAFE_IMPORTS:
        raise ImportError(f"Import of {name!r} is not allowed in skill sandbox")
    return _real_import(name, globals, locals, fromlist, level)


# Restricted builtins: no exec/eval/compile, safe open/__import__ only.
_builtins = {
    name: getattr(_builtins_module, name)
    for name in _SAFE_BUILTINS
    if hasattr(_builtins_module, name)
}
_builtins["open"] = _safe_open
_builtins["__import__"] = _safe_import


# Patch pathlib write helpers as well.
_original_pathlib_path_write_text = pathlib.Path.write_text
_original_pathlib_path_write_bytes = pathlib.Path.write_bytes
_original_pathlib_path_open = pathlib.Path.open


def _safe_path_write_text(self, *args, **kwargs):
    _check_path(self, "write")
    return _original_pathlib_path_write_text(self, *args, **kwargs)


def _safe_path_write_bytes(self, *args, **kwargs):
    _check_path(self, "write")
    return _original_pathlib_path_write_bytes(self, *args, **kwargs)


def _safe_path_open(self, mode="r", *args, **kwargs):
    if _is_write_mode(mode):
        _check_path(self, "write")
    return _original_pathlib_path_open(self, mode, *args, **kwargs)


pathlib.Path.write_text = _safe_path_write_text
pathlib.Path.write_bytes = _safe_path_write_bytes
pathlib.Path.open = _safe_path_open


_USER_CODE = @@USER_CODE@@
exec(_USER_CODE, {
    "__builtins__": _builtins,
    "args": _ARGS,
    "os": _os_proxy,
    "pathlib": pathlib,
    "json": json,
})
'''


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

    def execute(self, arguments: dict[str, Any]) -> SkillExecutionResult:
        if self._manifest is None:
            self._load()
        if self._run_code is None:
            return SkillExecutionResult(success=False, output="", error="No run.py found")

        timeout = self.manifest.timeout
        for key in self.manifest.parameters:
            if key not in arguments:
                arguments[key] = ""

        args_json = json.dumps(arguments, ensure_ascii=False)
        skill_dir = self._dir.resolve()

        with tempfile.TemporaryDirectory(prefix="lumina-skill-") as tmpdir:
            sandbox_dir = Path(tmpdir)
            script_path = sandbox_dir / "__sandbox__.py"
            script_path.write_text(
                self._build_sandbox_script(),
                encoding="utf-8",
            )

            proc = subprocess.Popen(
                [
                    "python3",
                    str(script_path),
                    args_json,
                    str(sandbox_dir),
                    str(skill_dir),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                cwd=str(sandbox_dir),
                start_new_session=True,
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Kill the entire process group to handle grandchildren.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                proc.communicate()
                return SkillExecutionResult(
                    success=False, output="", error=f"Timeout after {timeout}s"
                )
            except Exception as exc:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                proc.communicate()
                return SkillExecutionResult(success=False, output="", error=str(exc))

            output = (stdout or "").strip()
            error = (stderr or "").strip() if stderr else None
            return SkillExecutionResult(
                success=proc.returncode == 0,
                output=output or "(no output)",
                error=error,
                exit_code=proc.returncode if proc.returncode is not None else 1,
            )

    def _build_sandbox_script(self) -> str:
        safe_imports = ",".join(repr(name) for name in sorted(_SAFE_IMPORTS))
        safe_builtins = ",".join(repr(name) for name in sorted(_SAFE_BUILTINS))
        return (
            _SANDBOX_PREAMBLE
            .replace("@@SAFE_IMPORTS@@", safe_imports)
            .replace("@@SAFE_BUILTINS@@", safe_builtins)
            .replace("@@USER_CODE@@", repr(self._run_code))
        )

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
        skills_dir = self.skills_dir
        if not skills_dir.exists():
            return skills
        for folder in sorted(skills_dir.iterdir()):
            if not folder.is_dir():
                continue
            if (folder / SKILL_MD_FILE).exists() or (folder / MANIFEST_FILE).exists():
                skills.append(ExecutableSkill(folder))
        return skills

    def get_skill(self, name: str) -> ExecutableSkill | None:
        skills_dir = self.skills_dir
        direct = skills_dir / name
        if direct.is_dir():
            return ExecutableSkill(direct)
        if not skills_dir.exists():
            return None
        for folder in skills_dir.iterdir():
            if not folder.is_dir():
                continue
            skill = ExecutableSkill(folder)
            if skill.manifest.name == name:
                return skill
        return None

    def execute_skill(
        self, name: str, arguments: dict[str, Any]
    ) -> SkillExecutionResult:
        skill = self.get_skill(name)
        if skill is None:
            raise AgentError(f"Skill not found: {name}")
        if not skill.is_executable:
            raise AgentError(f"Skill '{name}' is prompt-only, not executable")
        return skill.execute(arguments)

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
