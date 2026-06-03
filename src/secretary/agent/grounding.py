"""Detect filesystem questions, collect read evidence, verify replies."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

READ_TOOL_NAMES = frozenset({"list_dir", "file_read", "search_files"})
MEMORY_TOOL_NAMES = frozenset({"search_memory", "session_search"})

_PERSONAL_MEMORY_MARKERS = (
    "在读",
    "读过",
    "阅读",
    "读书",
    "书目",
    "书籍",
    "书《",
    "记忆",
    "说过",
    "之前说",
    "上次",
    "历史对话",
    "近期",
    "最近读",
    "微信读书",
    "weread",
    "同步过",
    "个人经历",
    "再找",
    "再查",
    "重新找",
    "重新查",
)

_CHAT_HISTORY_EVIDENCE_MARKERS = (
    "翻了对话历史",
    "对话历史",
    "聊天记录",
    "你提到过",
    "你之前说",
    "你说过",
    "没有其他阅读",
    "没有新的阅读",
    "就这两本",
    "只有这两",
)

_FILE_QUESTION_MARKERS = (
    "文件",
    "目录",
    "路径",
    "文件夹",
    "readme",
    "代码库",
    "项目结构",
    "仓库",
    "本地",
    "磁盘",
    "打开",
    "读一下",
    "读取",
    "看看",
    "列出",
    "列出来",
    "列出所有",
    "有哪些",
    "哪些项目",
    "手上",
    "my project",
    "my projects",
    "所有文件",
    "简历",
    "文件夹",
    "跑一下",
    "ls ",
    "ls\n",
    "cat ",
    "有没有",
    "内容是什么",
    "里面有什么",
    "作者是谁",
    "作者",
    "谁写的",
    "谁开发",
    "维护者",
    "package.json",
    "readme",
    "src/",
    "config/",
    ".py",
    ".js",
    ".ts",
    ".json",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    "list_dir",
    "file_read",
    "search_files",
)

_CJK_START = re.compile(r"[\u4e00-\u9fff]")
_PATH_PATTERNS = (
    re.compile(
        r"(?:~/[^\s\u4e00-\u9fff\"'`<>|，。；;!?]+|"
        r"/Users/[^/\s\u4e00-\u9fff\"'`<>|]+(?:/[^\s\u4e00-\u9fff\"'`<>|，。；;!?]+)*)"
    ),
    re.compile(
        r"/(?:[A-Za-z0-9_.]+)(?:/(?:[A-Za-z0-9_.][A-Za-z0-9_. -]*))*"
    ),
    re.compile(r"(?:\./|\../)[^\s\"'`]+"),
    re.compile(r"\b[\w./-]+\.(?:py|js|ts|tsx|jsx|json|md|yaml|yml|toml|txt|csv)\b", re.IGNORECASE),
    re.compile(r"`([^`]+\.(?:py|js|ts|md|json|yaml|yml|toml|txt))`"),
)

_DEFERRAL_MARKERS = (
    "稍等",
    "等一下",
    "等等",
    "查完",
    "马上",
    "我去查",
    "我再查",
    "正在查",
    "稍后",
    "一会儿",
    "待会",
    "完成后",
    "告诉你",
    "回复你",
)

_MCP_READ_HINTS = ("read", "list", "search", "glob", "directory", "file")
_MCP_DIR_LINE = re.compile(r"^\s*\[DIR\]\s+(.+?)\s*$", re.MULTILINE)
_MCP_FILE_LINE = re.compile(r"^\s*\[FILE\]\s+(.+?)\s*$", re.MULTILINE)
_MY_PROJECTS_DIR = Path.home() / "Documents" / "My Projects"
_FILE_HEADER = re.compile(r"^📄\s+(\S+)", re.MULTILINE)
_DIR_HEADER = re.compile(r"^📂\s+(\S+)", re.MULTILINE)
_LISTED_FILE = re.compile(r"📄\s+(\S+)")
_NOT_FOUND = re.compile(r"(?:file not found|path not found|not a file):\s*(\S+)", re.IGNORECASE)
_SIMULATED_LS = re.compile(r"^\s*\$\s*ls\b", re.MULTILINE)
_SIMULATED_TOTAL = re.compile(r"^total\s+\d+", re.MULTILINE)
_SIMULATED_DRWX = re.compile(r"^[-drwxl]{10}\s+\d+\s+", re.MULTILINE)
_TREE_LINE = re.compile(r"^[├└│──]")
_FAKE_DIR_HEADER = re.compile(r"^📂\s+/", re.MULTILINE)

UNGROUNDED_LISTING_FALLBACK = (
    "我无法确认该目录下的真实文件名——本轮没有成功调用 list_dir / file_read / search_files，"
    "或工具结果不足以支撑当前回答。\n"
    "请再发一次「列出 ~/Documents/简历/ 里所有文件」，我会在进度里显示「浏览目录」或「搜索文件」后再回答；"
    "或者你在终端运行 `ls ~/Documents/简历/` 把输出贴给我。"
)

UNGROUNDED_MEMORY_FALLBACK = (
    "我无法核实你的阅读或个人记录——本轮没有调用 search_memory / session_search，"
    "不能把对话里助手自己说过的话当成事实。\n"
    "请点右上角「同步」导入微信读书等数据，或直接告诉我书名；"
    "也可以说「搜索记忆里我读过的书」让我先查本地记忆库。"
)


@dataclass
class ReadEvidence:
    read_files: set[str] = field(default_factory=set)
    listed_dirs: set[str] = field(default_factory=set)
    listed_names: set[str] = field(default_factory=set)
    search_hits: set[str] = field(default_factory=set)
    not_found: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    unverified_paths: tuple[str, ...] = ()
    note: str = ""


def is_filesystem_question(message: str) -> bool:
    text = message.strip()
    if not text:
        return False
    lowered = text.lower()
    if any(marker in text or marker in lowered for marker in _FILE_QUESTION_MARKERS):
        return True
    return any(pattern.search(text) for pattern in _PATH_PATTERNS)


def mentions_local_files(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    if any(pattern.search(cleaned) for pattern in _PATH_PATTERNS):
        return True
    file_talk = (
        "这个文件",
        "该文件",
        "目录下",
        "项目里",
        "代码里",
        "根目录",
        "子目录",
        "配置文件",
    )
    return any(marker in cleaned for marker in file_talk)


def is_personal_memory_question(message: str) -> bool:
    text = message.strip()
    if not text:
        return False
    lowered = text.lower()
    return any(marker in text or marker in lowered for marker in _PERSONAL_MEMORY_MARKERS)


def has_read_grounding(used_tools: list[str]) -> bool:
    for name in used_tools:
        if name in READ_TOOL_NAMES:
            return True
        lowered = name.lower()
        if name.startswith("mcp_") and any(hint in lowered for hint in _MCP_READ_HINTS):
            return True
    return False


def has_memory_grounding(used_tools: list[str]) -> bool:
    return any(name in MEMORY_TOOL_NAMES for name in used_tools)


def reply_cites_chat_history_as_fact(reply: str) -> bool:
    text = reply.strip()
    if not text:
        return False
    return any(marker in text for marker in _CHAT_HISTORY_EVIDENCE_MARKERS)


def reply_defers_filesystem_work(reply: str) -> bool:
    """Model promised to check later without calling tools in this turn."""
    text = reply.strip()
    if not text:
        return False
    return any(marker in text for marker in _DEFERRAL_MARKERS)


def _normalize_path_token(raw: str) -> str:
    token = raw.strip().strip("`\"'").rstrip("。，,.!?；;")
    match = _CJK_START.search(token)
    if match and match.start() > 0:
        token = token[: match.start()].rstrip("/ ").strip()
    return token


def _extract_path_candidates(text: str) -> list[str]:
    found: list[str] = []
    for pattern in _PATH_PATTERNS:
        for match in pattern.finditer(text):
            token = _normalize_path_token(match.group(0))
            if len(token) >= 3:
                found.append(token)
    return found


def infer_list_dir_target(user_message: str, reply: str = "") -> str | None:
    """Best-effort directory path from user text or assistant reply."""
    candidates: list[str] = []
    for text in (user_message, reply):
        candidates.extend(_extract_path_candidates(text))
        lowered = text.lower()
        if re.search(r"my\s*projects?", lowered) or "my project" in lowered:
            candidates.append(str(_MY_PROJECTS_DIR))
        if "我的项目" in text or "哪些项目" in text:
            candidates.append(str(_MY_PROJECTS_DIR))
    if not candidates:
        return None

    resolved: list[Path] = []
    for token in sorted(set(candidates), key=len, reverse=True):
        try:
            path = Path(token).expanduser()
        except (OSError, ValueError):
            continue
        if path.is_dir():
            resolved.append(path.resolve())
            continue
        parent = path.parent
        if parent.is_dir() and token.rstrip().endswith("/"):
            resolved.append(parent.resolve())

    if resolved:
        return str(resolved[0])

    for token in sorted(set(candidates), key=len, reverse=True):
        if token.startswith("~") or token.startswith("/"):
            return token
    return candidates[0]


def should_retry_for_grounding(
    user_message: str,
    reply: str,
    used_tools: list[str],
) -> bool:
    if has_read_grounding(used_tools):
        return False
    if reply_simulates_file_listing(reply):
        return True
    if not is_filesystem_question(user_message):
        return False
    if reply_defers_filesystem_work(reply):
        return True
    if mentions_local_files(reply):
        return True
    return True


def reply_simulates_file_listing(reply: str) -> bool:
    """Detect fake ls output, directory trees, or bulk filename lists."""
    text = reply.strip()
    if not text:
        return False
    if (
        _SIMULATED_LS.search(text)
        or _SIMULATED_TOTAL.search(text)
        or _SIMULATED_DRWX.search(text)
        or _FAKE_DIR_HEADER.search(text)
    ):
        return True
    tree_lines = sum(1 for line in text.splitlines() if _TREE_LINE.match(line.strip()))
    if tree_lines >= 2:
        return True
    md_count = len(re.findall(r"[\w.-]+\.md\b", text, re.IGNORECASE))
    if md_count >= 3 and (tree_lines >= 1 or "├──" in text or "└──" in text):
        return True
    if md_count >= 5:
        return True
    return False


def requires_forced_read_tool(user_message: str, used_tools: list[str]) -> bool:
    return is_filesystem_question(user_message) and not has_read_grounding(used_tools)


def strip_forbidden_listing_patterns(reply: str) -> str:
    """Remove simulated ls / directory-tree lines from user-facing text."""
    lines = reply.splitlines()
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        if (
            _SIMULATED_LS.match(stripped)
            or _SIMULATED_TOTAL.match(stripped)
            or _SIMULATED_DRWX.match(stripped)
            or _FAKE_DIR_HEADER.match(stripped)
            or _TREE_LINE.match(stripped)
        ):
            continue
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    if reply_simulates_file_listing(reply) and not cleaned:
        return ""
    return cleaned


def sanitize_filesystem_reply(reply: str) -> str:
    cleaned = strip_forbidden_listing_patterns(reply)
    return cleaned.strip()


def reply_fabricates_file_inspection(reply: str) -> bool:
    """Claims to have opened/read specific project files without tool evidence."""
    text = reply.strip().lower()
    if not text:
        return False
    markers = (
        "package.json",
        "readme.md",
        "readme",
        "author 字段",
        "authors",
        "我查了",
        "我读了",
        "重新查",
        "打开看了",
        "读取了",
        "文件里",
        "字段为",
    )
    return any(marker in text for marker in markers)


def reply_injects_lumina_identity_as_project_author(reply: str) -> bool:
    """Blocks answering 四海 / Lumina dev as a repo author without tool proof."""
    if "四海" not in reply:
        return False
    return any(
        marker in reply
        for marker in ("作者", "author", "开发者", "维护者", "谁写", "谁开发")
    )


def enforce_grounded_reply(
    reply: str,
    user_message: str,
    used_tools: list[str],
    *,
    grounding_verified: bool,
    grounding_note: str,
) -> tuple[str, bool, str]:
    """Replace hallucinated directory listings when tools were not used."""
    reply = sanitize_filesystem_reply(reply)
    # Tool-backed replies that passed verification may list many filenames (e.g. search_files
    # hits); reply_simulates_file_listing would false-positive on those.
    if has_read_grounding(used_tools):
        if grounding_verified:
            return reply, grounding_verified, grounding_note
        if not (
            reply_simulates_file_listing(reply)
            or reply_fabricates_file_inspection(reply)
            or reply_injects_lumina_identity_as_project_author(reply)
        ):
            note = grounding_note or "已通过 list_dir / file_read / MCP 读盘工具核实"
            return reply, True, note

    if is_filesystem_question(user_message) and not has_read_grounding(used_tools):
        note = grounding_note or "未调用 list_dir / file_read / search_files，已阻止未核实内容"
        return UNGROUNDED_LISTING_FALLBACK, False, note

    if is_personal_memory_question(user_message) and not has_memory_grounding(used_tools):
        note = grounding_note or "未调用 search_memory / session_search，已阻止未核实的个人记录"
        return UNGROUNDED_MEMORY_FALLBACK, False, note

    if reply_cites_chat_history_as_fact(reply) and not has_memory_grounding(used_tools):
        note = grounding_note or "回复仅引用对话历史，未检索本地记忆"
        return UNGROUNDED_MEMORY_FALLBACK, False, note

    risky = reply_simulates_file_listing(reply) or (
        mentions_local_files(reply)
        or reply_defers_filesystem_work(reply)
        or reply_fabricates_file_inspection(reply)
        or reply_injects_lumina_identity_as_project_author(reply)
    )
    if not risky:
        return reply, grounding_verified, grounding_note

    note = grounding_note or "未调用文件工具，已阻止展示可能虚构的目录/文件列表"
    return UNGROUNDED_LISTING_FALLBACK, False, note


def collect_read_evidence(steps: list[Any]) -> ReadEvidence:
    evidence = ReadEvidence()
    for step in steps:
        tool_call = getattr(step, "tool_call", None)
        tool_output = getattr(step, "tool_output", None)
        if tool_call is None or not tool_output:
            continue
        name = str(getattr(tool_call, "name", "") or "")
        arguments = getattr(tool_call, "arguments", {}) or {}
        output = str(tool_output)
        _absorb_not_found(evidence, output)
        if name == "file_read":
            _absorb_file_read(evidence, arguments, output)
        elif name == "list_dir":
            _absorb_list_dir(evidence, output)
        elif name == "search_files":
            _absorb_search_files(evidence, output)
        elif name.startswith("mcp_"):
            _absorb_mcp_output(evidence, output, arguments)
    return evidence


def verify_reply_against_evidence(
    reply: str,
    evidence: ReadEvidence,
    user_message: str,
) -> VerificationResult:
    if not is_filesystem_question(user_message):
        return VerificationResult(ok=True)

    if reply_simulates_file_listing(reply) and not has_evidence(evidence):
        return VerificationResult(
            ok=False,
            note="回复疑似伪造目录列表或 ls 输出，但未调用 list_dir/file_read",
        )

    if not has_evidence(evidence):
        if reply_defers_filesystem_work(reply):
            return VerificationResult(
                ok=False,
                note="回复声称稍后再查，但未在本轮调用 list_dir/file_read/search_files",
            )
        if mentions_local_files(reply):
            return VerificationResult(
                ok=False,
                note="回复含路径但未调用文件工具核实",
            )
        return VerificationResult(ok=True)

    claimed = _extract_claimed_references(reply)
    if not claimed:
        return VerificationResult(ok=True)

    known = _known_reference_set(evidence)
    unverified: list[str] = []
    for ref in sorted(claimed):
        ref_norm = _norm_token(ref)
        if ref_norm in evidence.not_found or _basename(ref_norm) in evidence.not_found:
            unverified.append(ref)
            continue
        if not _ref_is_grounded(ref_norm, known, evidence):
            unverified.append(ref)

    if unverified:
        preview = "、".join(unverified[:4])
        if len(unverified) > 4:
            preview += "…"
        return VerificationResult(
            ok=False,
            unverified_paths=tuple(unverified),
            note=f"以下路径/文件名未出现在工具返回中：{preview}",
        )
    return VerificationResult(ok=True)


def should_retry_for_verification(verification: VerificationResult) -> bool:
    return not verification.ok


def format_verify_retry(verification: VerificationResult, evidence: ReadEvidence) -> str:
    read_list = "、".join(sorted(evidence.read_files | evidence.search_hits)[:6]) or "（无）"
    listed = "、".join(sorted(evidence.listed_names)[:6]) or "（无）"
    return (
        f"[System] 回复二次验证未通过：{verification.note}\n"
        f"已通过工具读到的文件：{read_list}\n"
        f"目录列表中出现的文件名：{listed}\n"
        "请仅基于上述工具结果重写回答；未读到的不要说「有」或编造内容；"
        "若工具返回 Error/not found，应明确告知用户未找到。"
    )


def evidence_summary(evidence: ReadEvidence) -> str:
    parts: list[str] = []
    if evidence.read_files:
        parts.append(f"已读 {len(evidence.read_files)} 个文件")
    if evidence.listed_dirs:
        parts.append(f"已列 {len(evidence.listed_dirs)} 个目录")
    if evidence.search_hits:
        parts.append(f"搜索命中 {len(evidence.search_hits)} 个路径")
    return " · ".join(parts) if parts else ""


GROUNDING_RETRY_USER = (
    "[System] 你尚未用 list_dir、file_read 或 search_files 核实本地文件系统，"
    "禁止编造路径、文件名或文件内容；禁止在正文里伪造 `$ ls` 输出、目录树（├──）或假装已列目录。"
    "禁止只说「稍等」「查完告诉你」却不调用工具——必须在本轮内完成 list_dir 并给出结果。"
    "请先调用只读工具查证，再仅复述工具返回的原始结果。"
    "若文件不存在，明确说「未找到」，不要猜测。"
)


def _has_evidence(evidence: ReadEvidence) -> bool:
    return bool(
        evidence.read_files
        or evidence.listed_dirs
        or evidence.listed_names
        or evidence.search_hits
    )


has_evidence = _has_evidence


def _norm_path(value: str) -> str:
    try:
        return str(Path(value).expanduser().resolve()).lower()
    except (OSError, ValueError):
        return str(Path(value).expanduser()).lower()


def _basename(value: str) -> str:
    return Path(value).name.lower()


def _norm_token(value: str) -> str:
    cleaned = value.strip().strip("`\"'")
    if "/" in cleaned or cleaned.startswith("~"):
        return _norm_path(cleaned)
    return cleaned.lower()


def _known_reference_set(evidence: ReadEvidence) -> set[str]:
    known: set[str] = set()
    for item in evidence.read_files | evidence.search_hits | evidence.listed_dirs:
        known.add(item)
        known.add(_basename(item))
    known.update(name.lower().rstrip() for name in evidence.listed_names)
    return known


def _ref_is_grounded(ref: str, known: set[str], evidence: ReadEvidence) -> bool:
    ref_l = ref.lower()
    base = _basename(ref_l)
    if ref_l in known or base in known:
        return True
    for item in known:
        if item.endswith("/" + base) or item.endswith(base):
            return True
    for listed in evidence.listed_names:
        listed_l = listed.lower().rstrip()
        if listed_l == base or base.endswith("/" + listed_l):
            return True
    return False


def _extract_claimed_references(reply: str) -> set[str]:
    refs: set[str] = set()
    for pattern in _PATH_PATTERNS:
        for match in pattern.findall(reply):
            token = match if isinstance(match, str) else match[0]
            cleaned = token.strip().strip("`\"'")
            if len(cleaned) >= 3:
                refs.add(cleaned)
    return refs


def _absorb_not_found(evidence: ReadEvidence, output: str) -> None:
    for match in _NOT_FOUND.finditer(output):
        evidence.not_found.add(_norm_token(match.group(1)))


def _absorb_file_read(evidence: ReadEvidence, arguments: dict[str, Any], output: str) -> None:
    arg_path = str(arguments.get("path", "")).strip()
    if output.startswith("Error:"):
        if arg_path:
            evidence.not_found.add(_norm_token(arg_path))
        return
    header = _FILE_HEADER.search(output)
    if header:
        evidence.read_files.add(_norm_path(header.group(1)))
    elif arg_path:
        evidence.read_files.add(_norm_token(arg_path))


def _absorb_list_dir(evidence: ReadEvidence, output: str) -> None:
    header = _DIR_HEADER.search(output)
    if header:
        evidence.listed_dirs.add(_norm_path(header.group(1)))
    for match in _LISTED_FILE.finditer(output):
        name = match.group(1).split()[0]
        evidence.listed_names.add(name)


def _absorb_search_files(evidence: ReadEvidence, output: str) -> None:
    for line in output.splitlines():
        if ":" not in line or line.startswith("Error:"):
            continue
        path = line.split(":", 1)[0].strip()
        if path:
            evidence.search_hits.add(_norm_path(path))


def _absorb_mcp_output(
    evidence: ReadEvidence,
    output: str,
    arguments: dict[str, Any] | None = None,
) -> None:
    if output.startswith("Error:"):
        return
    if arguments:
        base = str(arguments.get("path", "") or arguments.get("directory", "")).strip()
        if base:
            try:
                evidence.listed_dirs.add(_norm_path(str(Path(base).expanduser())))
            except (OSError, ValueError):
                evidence.listed_dirs.add(_norm_token(base))
    for match in _PATH_PATTERNS[0].finditer(output):
        evidence.read_files.add(_norm_path(match.group(0)))
    for match in _LISTED_FILE.finditer(output):
        evidence.listed_names.add(match.group(1).split()[0])
    for match in _MCP_DIR_LINE.finditer(output):
        name = match.group(1).strip().rstrip("/")
        if name:
            evidence.listed_names.add(name)
    for match in _MCP_FILE_LINE.finditer(output):
        name = match.group(1).strip()
        if name:
            evidence.listed_names.add(name)
    try:
        import json

        payload = json.loads(output)
    except json.JSONDecodeError:
        return
    _walk_json_paths(evidence, payload)


def _walk_json_paths(evidence: ReadEvidence, node: Any) -> None:
    if isinstance(node, str) and ("/" in node or node.endswith((".py", ".md", ".json", ".txt"))):
        evidence.read_files.add(_norm_token(node))
    elif isinstance(node, dict):
        for value in node.values():
            _walk_json_paths(evidence, value)
    elif isinstance(node, list):
        for value in node:
            _walk_json_paths(evidence, value)
