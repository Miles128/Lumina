"""OpenAI-compatible chat completion client with httpx and retry logic."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from secretary.agent.llm_config import LlmConfig
from secretary.exceptions import AgentError

logger = logging.getLogger(__name__)

Role = Literal["system", "user", "assistant", "tool"]

_MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 1.0
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.NetworkError):
        return True
    if isinstance(exc, httpx.RemoteProtocolError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUSES
    return False


def _sleep_for_retry(attempt: int) -> None:
    delay = _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
    time.sleep(delay)


def _build_http_client(timeout: float) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(timeout, connect=15.0),
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
    )


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


class _UsageScope:
    """Manual context manager (avoiding @contextmanager typing issues with mypy strict)."""

    def __init__(self) -> None:
        self._usage = LlmUsage()
        self._token: Any = None

    def __enter__(self) -> LlmUsage:
        self._token = _USAGE_TRACKER.set(self._usage)
        return self._usage

    def __exit__(self, *args: object) -> None:
        if self._token is not None:
            _USAGE_TRACKER.reset(self._token)
            self._token = None


def llm_usage_scope() -> _UsageScope:
    """Track token usage across multiple LLM calls in a single scope.

    Usage:
        with llm_usage_scope() as usage:
            reply = chat_completion(config, messages)
            print(usage.total_tokens)
    """
    return _UsageScope()


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
    last_error: str | None = None
    with _build_http_client(timeout) as client:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return _stream_request(client, url, payload, config.api_key, on_delta)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = str(exc)
                logger.warning("LLM stream attempt %d/%d failed: %s", attempt, _MAX_RETRIES, exc)
                if attempt < _MAX_RETRIES:
                    _sleep_for_retry(attempt)
            except httpx.HTTPStatusError as exc:
                detail = _read_error_body(exc)
                logger.warning("LLM stream HTTP error %s: %s", exc.response.status_code, detail[:300])
                if exc.response.status_code in _RETRYABLE_STATUSES and attempt < _MAX_RETRIES:
                    _sleep_for_retry(attempt)
                    continue
                message = _extract_api_error(detail) or f"大模型请求失败 ({exc.response.status_code})"
                raise AgentError(message) from exc
    raise AgentError(f"大模型流式请求失败（{_MAX_RETRIES} 次重试后）: {last_error or '未知错误'}")


def _stream_request(
    client: httpx.Client,
    url: str,
    payload: dict[str, Any],
    api_key: str,
    on_delta: Callable[[str], None],
) -> str:
    parts: list[str] = []
    with client.stream(
        "POST",
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
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
    last_error: str | None = None
    with _build_http_client(timeout) as client:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return _tools_request(client, url, payload, config.api_key)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = str(exc)
                logger.warning("LLM tools attempt %d/%d failed: %s", attempt, _MAX_RETRIES, exc)
                if attempt < _MAX_RETRIES:
                    _sleep_for_retry(attempt)
            except httpx.HTTPStatusError as exc:
                detail = _read_error_body(exc)
                logger.warning("LLM tools HTTP error %s: %s", exc.response.status_code, detail[:300])
                if exc.response.status_code in _RETRYABLE_STATUSES and attempt < _MAX_RETRIES:
                    _sleep_for_retry(attempt)
                    continue
                message = _extract_api_error(detail) or f"大模型工具调用失败 ({exc.response.status_code})"
                raise AgentError(message) from exc
    raise AgentError(f"大模型工具调用失败（{_MAX_RETRIES} 次重试后）: {last_error or '未知错误'}")


def _tools_request(
    client: httpx.Client,
    url: str,
    payload: dict[str, Any],
    api_key: str,
) -> ChatCompletionResult:
    response = client.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    response.raise_for_status()
    body = response.json()
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
    # DeepSeek thinking mode requires reasoning_content on tool-call turns to be
    # replayed on every subsequent request; dropping it yields HTTP 400.
    reasoning = message.get("reasoning_content")
    if tool_calls:
        result: dict[str, Any] = {
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
        if isinstance(reasoning, str):
            result["reasoning_content"] = reasoning
        return result
    result = {"role": "assistant", "content": content}
    if isinstance(reasoning, str) and reasoning:
        result["reasoning_content"] = reasoning
    return result


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
) -> str:
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
    }
    last_error: str | None = None
    with _build_http_client(timeout) as client:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                body = _non_stream_request(client, url, payload, config.api_key)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = str(exc)
                logger.warning("LLM attempt %d/%d failed: %s", attempt, _MAX_RETRIES, exc)
                if attempt < _MAX_RETRIES:
                    _sleep_for_retry(attempt)
                continue
            except httpx.HTTPStatusError as exc:
                detail = _read_error_body(exc)
                logger.warning("LLM HTTP error %s: %s", exc.response.status_code, detail[:300])
                if exc.response.status_code in _RETRYABLE_STATUSES and attempt < _MAX_RETRIES:
                    _sleep_for_retry(attempt)
                    continue
                message = _extract_api_error(detail) or f"大模型请求失败 ({exc.response.status_code})"
                raise AgentError(message) from exc

            _record_usage(body.get("usage"))
            try:
                message = body["choices"][0]["message"]
            except (KeyError, IndexError, TypeError) as error:
                raise AgentError("大模型返回格式异常") from error
            content = _extract_message_text(message)
            if content:
                return content
            # Empty content — retry once more specifically
            if attempt < _MAX_RETRIES:
                logger.warning("LLM returned empty content, retrying (attempt %d/%d)", attempt, _MAX_RETRIES)
                _sleep_for_retry(attempt)
                continue
    raise AgentError(f"大模型请求失败（{_MAX_RETRIES} 次重试后）: {last_error or '大模型返回空内容'}")


def _non_stream_request(
    client: httpx.Client,
    url: str,
    payload: dict[str, Any],
    api_key: str,
) -> dict[str, Any]:
    response = client.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    response.raise_for_status()
    return response.json()  # type: ignore[no-any-return]


def _read_error_body(exc: httpx.HTTPStatusError) -> str:
    try:
        return exc.response.text
    except Exception:
        return ""


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
        parsed = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0
