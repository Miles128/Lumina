"""Base types shared between loop.py and tools modules (avoid circular imports)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = ""


@dataclass(frozen=True)
class ToolResult:
    """工具执行的统一返回类型，支持结构化错误回传。

    - content: 成功时的输出内容（字符串）
    - error: 失败时的错误消息（字符串），成功时为 None
    - error_type: 错误分类（"not_found" / "permission" / "timeout" / "validation" / "internal"），
      成功时为 None
    - retryable: 该错误是否值得 LLM 重试（如超时/临时错误为 True，路径不存在/权限不足为 False）
    """

    content: str = ""
    error: str | None = None
    error_type: str | None = None
    retryable: bool = False

    @property
    def success(self) -> bool:
        return self.error is None

    @classmethod
    def failure(
        cls,
        message: str,
        *,
        error_type: str = "internal",
        retryable: bool = False,
    ) -> ToolResult:
        """构造一个结构化错误结果。"""
        return cls(error=message, error_type=error_type, retryable=retryable)

    def to_output_string(self) -> str:
        """转为回灌给 LLM 的字符串表示。"""
        if self.success:
            return self.content
        hint = "可重试" if self.retryable else "不可重试，请换一种方式"
        return f"[ERROR type={self.error_type or 'internal'} retryable={self.retryable}] {self.error}（{hint}）"


def _classify_error_string(text: str) -> tuple[str, bool]:
    """根据 Error 字符串内容启发式分类错误。

    返回 (error_type, retryable)。用于兼容仍返回 "Error: ..." 字符串的工具。
    """
    lowered = text.lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout", True
    if "not found" in lowered or "no such file" in lowered or "does not exist" in lowered:
        return "not_found", False
    if "permission denied" in lowered or "access denied" in lowered:
        return "permission", False
    if "empty command" in lowered or "invalid" in lowered or "bad" in lowered:
        return "validation", False
    return "internal", False


def _coerce_to_tool_result(raw: str | ToolResult, tool_name: str = "") -> ToolResult:
    """把工具输出统一转为 ToolResult。

    - 已经是 ToolResult 的直接返回
    - 以 "Error:" 开头的字符串按内容分类为错误
    - 其他字符串视为成功 content

    已知限制：仅通过首行 "Error:" 前缀启发式判断错误。若工具返回的
    成功内容首行恰好以 "Error:" 开头（如输出恰好为 "Error: ..." 的文件内容），
    会被误判为错误。建议新工具直接返回 ToolResult.failure() 以避免此问题。
    """
    if isinstance(raw, ToolResult):
        return raw
    text = raw if isinstance(raw, str) else str(raw)
    if text.startswith("Error:"):
        error_type, retryable = _classify_error_string(text)
        return ToolResult.failure(text, error_type=error_type, retryable=retryable)
    return ToolResult(content=text)


def _resolve_path(raw: str, working_dir: Path) -> Path:
    """Resolve a tool path against working_dir, expanding ``~`` / ``~user``."""
    path = Path(raw or ".").expanduser()
    if not path.is_absolute():
        path = working_dir / path
    return path.resolve()


class Tool:
    name: str = ""
    description: str = ""
    needs_confirmation: bool = False
    risk_level: str = "low"
    # read_only: 工具是否只读取信息、不修改外部状态。
    # 读工具跳过确认门；写工具/状态变更工具需要确认。
    read_only: bool = False

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self._parameters(),
            "needs_confirmation": self.needs_confirmation,
        }

    def _parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        raise NotImplementedError

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return f"Execute {self.name}"
