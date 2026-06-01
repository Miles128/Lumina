"""OpenAI-compatible chat completion client."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal

from secretary.agent.llm_config import LlmConfig
from secretary.exceptions import AgentError

logger = logging.getLogger(__name__)

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class LlmUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class LlmToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatCompletionResult:
    content: str
    tool_calls: tuple[LlmToolCall, ...]
    assistant_message: dict[str, Any]


_USAGE_TRACKER: ContextVar[LlmUsage | None] = ContextVar(
    "llm_usage_tracker",
    default=None,
)


@contextmanager
def llm_usage_scope() -> LlmUsage:
    usage = LlmUsage()
    token = _USAGE_TRACKER.set(usage)
    try:
        yield usage
    finally:
        _USAGE_TRACKER.reset(token)


def chat_completion(
    config: LlmConfig,
    messages: list[dict[str, str]],
    *,
    timeout: float = 120.0,
    temperature: float = 0.7,
    on_delta: Callable[[str], None] | None = None,
) -> str:
    if on_delta is None:
        return _chat_completion_once(
            config,
            messages,
            timeout=timeout,
            temperature=temperature,
            allow_retry=True,
        )
    return chat_completion_stream(
        config,
        messages,
        on_delta=on_delta,
        timeout=timeout,
        temperature=temperature,
    )


def chat_completion_stream(
    config: LlmConfig,
    messages: list[dict[str, str]],
    *,
    on_delta: Callable[[str], None],
    timeout: float = 120.0,
    temperature: float = 0.7,
) -> str:
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    parts: list[str] = []
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for line in _iter_sse_lines(response):
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                usage = chunk.get("usage")
                if isinstance(usage, dict):
                    _record_usage(usage)
                delta = _extract_stream_delta(chunk)
                if delta:
                    parts.append(delta)
                    on_delta(delta)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        logger.warning("LLM stream HTTP error %s: %s", error.code, detail[:300])
        message = _extract_api_error(detail) or f"大模型请求失败 ({error.code})"
        raise AgentError(message) from error
    except urllib.error.URLError as error:
        logger.warning("LLM stream network error: %s", error.reason)
        raise AgentError("无法连接大模型服务") from error
    except TimeoutError as error:
        raise AgentError("大模型响应超时") from error

    content = "".join(parts).strip()
    if not content:
        raise AgentError("大模型返回空内容")
    return content


def schemas_to_openai_tools(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for schema in schemas:
        name = str(schema.get("name") or "").strip()
        if not name:
            continue
        parameters = schema.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {"type": "object", "properties": {}}
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(schema.get("description") or ""),
                    "parameters": parameters,
                },
            }
        )
    return tools


def chat_completion_with_tools(
    config: LlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    tool_choice: str | dict[str, Any] = "auto",
    timeout: float = 120.0,
    temperature: float = 0.7,
) -> ChatCompletionResult:
    """Call /chat/completions with OpenAI-style function tools."""
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
        "tools": tools,
        "tool_choice": tool_choice,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        logger.warning("LLM tools HTTP error %s: %s", error.code, detail[:300])
        message = _extract_api_error(detail) or f"大模型工具调用失败 ({error.code})"
        raise AgentError(message) from error
    except urllib.error.URLError as error:
        logger.warning("LLM tools network error: %s", error.reason)
        raise AgentError("无法连接大模型服务") from error
    except TimeoutError as error:
        raise AgentError("大模型响应超时") from error

    _record_usage(body.get("usage"))
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as error:
        raise AgentError("大模型返回格式异常") from error
    if not isinstance(message, dict):
        raise AgentError("大模型返回格式异常")
    return _result_from_assistant_message(message)


def _result_from_assistant_message(message: dict[str, Any]) -> ChatCompletionResult:
    content = _extract_message_text(message)
    tool_calls = _parse_message_tool_calls(message)
    assistant_message = _assistant_message_dict(message, content, tool_calls)
    return ChatCompletionResult(
        content=content,
        tool_calls=tool_calls,
        assistant_message=assistant_message,
    )


def _parse_message_tool_calls(message: dict[str, Any]) -> tuple[LlmToolCall, ...]:
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list):
        return ()
    parsed: list[LlmToolCall] = []
    for index, item in enumerate(raw_calls):
        if not isinstance(item, dict):
            continue
        fn = item.get("function")
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        args_raw = fn.get("arguments", "{}")
        if isinstance(args_raw, dict):
            arguments = dict(args_raw)
        else:
            try:
                loaded = json.loads(str(args_raw or "{}"))
            except json.JSONDecodeError:
                loaded = {}
            arguments = loaded if isinstance(loaded, dict) else {}
        call_id = str(item.get("id") or f"call_{name}_{index}")
        parsed.append(LlmToolCall(id=call_id, name=name, arguments=arguments))
    return tuple(parsed)


def _assistant_message_dict(
    message: dict[str, Any],
    content: str,
    tool_calls: tuple[LlmToolCall, ...],
) -> dict[str, Any]:
    if tool_calls:
        return {
            "role": "assistant",
            "content": content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in tool_calls
            ],
        }
    return {"role": "assistant", "content": content}


def _iter_sse_lines(response: object) -> Iterator[str]:
    for raw in response:
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace").strip()
        if line:
            yield line


def _extract_stream_delta(chunk: dict[str, object]) -> str:
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return ""
    reasoning = delta.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return ""
    content = delta.get("content")
    if isinstance(content, str):
        return content
    return ""


def _chat_completion_once(
    config: LlmConfig,
    messages: list[dict[str, str]],
    *,
    timeout: float,
    temperature: float,
    allow_retry: bool,
) -> str:
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        logger.warning("LLM HTTP error %s: %s", error.code, detail[:300])
        message = _extract_api_error(detail) or f"大模型请求失败 ({error.code})"
        raise AgentError(message) from error
    except urllib.error.URLError as error:
        logger.warning("LLM network error: %s", error.reason)
        raise AgentError("无法连接大模型服务") from error
    except TimeoutError as error:
        raise AgentError("大模型响应超时") from error

    _record_usage(body.get("usage"))

    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as error:
        raise AgentError("大模型返回格式异常") from error
    content = _extract_message_text(message)
    if not content and allow_retry:
        logger.warning("LLM returned empty content, retrying once")
        return _chat_completion_once(
            config,
            messages,
            timeout=timeout,
            temperature=temperature,
            allow_retry=False,
        )
    if not content:
        raise AgentError("大模型返回空内容")
    return content


def _extract_api_error(detail: str) -> str | None:
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return detail[:180] if detail.strip() else None
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return None


def _extract_message_text(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
            elif isinstance(item, str) and item.strip():
                parts.append(item.strip())
        return "\n".join(parts).strip()
    return ""


def _record_usage(usage_payload: object) -> None:
    tracker = _USAGE_TRACKER.get()
    if tracker is None or not isinstance(usage_payload, dict):
        return

    prompt = _to_int(usage_payload.get("prompt_tokens"))
    if prompt == 0:
        prompt = _to_int(usage_payload.get("input_tokens"))

    completion = _to_int(usage_payload.get("completion_tokens"))
    if completion == 0:
        completion = _to_int(usage_payload.get("output_tokens"))

    total = _to_int(usage_payload.get("total_tokens"))
    if total == 0:
        total = prompt + completion

    tracker.prompt_tokens += prompt
    tracker.completion_tokens += completion
    tracker.total_tokens += total


def _to_int(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0
