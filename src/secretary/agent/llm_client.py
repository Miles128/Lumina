"""OpenAI-compatible chat completion client via the openai SDK."""

from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from secretary.agent.llm_config import LlmConfig, deepseek_beta_base_url, model_supports_thinking
from secretary.exceptions import AgentError

logger = logging.getLogger(__name__)

Role = Literal["system", "user", "assistant", "tool"]
ThinkingState = Literal["enabled", "disabled"]
ReasoningEffort = Literal["low", "high", "max"]

_MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 30.0
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


# Unified retry layer (no-reinventing rule): the openai client is created with
# max_retries=0, so THIS is the only retry/backoff for the direct/utility path.
# The agents-sdk path uses the SDK's built-in retries (separate async client).


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in _RETRYABLE_STATUSES
    return False


def _sleep_for_retry(attempt: int) -> None:
    """指数退避 + jitter：base * 2^(attempt-1) + 随机抖动，上限 _MAX_BACKOFF_SECONDS。"""
    delay = _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
    delay = min(delay, _MAX_BACKOFF_SECONDS)
    jitter = random.uniform(0, _BASE_BACKOFF_SECONDS)  # noqa: S311
    time.sleep(delay + jitter)


def _build_openai_client(
    config: LlmConfig,
    timeout: float,
    *,
    base_url: str | None = None,
) -> OpenAI:
    base = (base_url or config.base_url or "").rstrip("/")
    return OpenAI(
        api_key=config.api_key,
        base_url=base or None,
        max_retries=0,
        timeout=timeout,
    )


def _thinking_extra_body(payload: dict[str, Any]) -> dict[str, Any]:
    """DeepSeek thinking params go via extra_body on the OpenAI SDK."""
    extra: dict[str, Any] = {}
    thinking = payload.get("thinking")
    if isinstance(thinking, dict):
        extra["thinking"] = thinking
    effort = payload.get("reasoning_effort")
    if effort is not None:
        extra["reasoning_effort"] = effort
    return extra


def _completion_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    """Map our OpenAI-shaped payload to chat.completions.create kwargs."""
    kwargs: dict[str, Any] = {
        "model": payload["model"],
        "messages": payload["messages"],
    }
    if "temperature" in payload:
        kwargs["temperature"] = payload["temperature"]
    if "tools" in payload:
        kwargs["tools"] = payload["tools"]
    if "tool_choice" in payload:
        kwargs["tool_choice"] = payload["tool_choice"]
    if payload.get("stream"):
        kwargs["stream"] = True
    extra = _thinking_extra_body(payload)
    if extra:
        kwargs["extra_body"] = extra
    return kwargs


def _sdk_response_to_dict(response: Any) -> dict[str, Any]:
    """Normalize an OpenAI SDK ChatCompletion to a plain OpenAI-shaped dict.

    Reads fields via getattr (not model_dump) so DeepSeek-only fields survive:
    reasoning_content on the message, prompt_cache_hit/miss_tokens on usage.
    """
    choices_out: list[dict[str, Any]] = []
    for choice in getattr(response, "choices", None) or []:
        message = getattr(choice, "message", None)
        if message is None:
            choices_out.append({"message": {"role": "assistant", "content": ""}})
            continue
        msg_dict: dict[str, Any] = {
            "role": getattr(message, "role", "assistant"),
            "content": getattr(message, "content", "") or "",
        }
        reasoning = getattr(message, "reasoning_content", None)
        if isinstance(reasoning, str):
            msg_dict["reasoning_content"] = reasoning
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            serialized: list[dict[str, Any]] = []
            for call in tool_calls:
                fn = getattr(call, "function", None)
                if fn is None:
                    continue
                serialized.append(
                    {
                        "id": getattr(call, "id", ""),
                        "type": "function",
                        "function": {
                            "name": getattr(fn, "name", ""),
                            "arguments": getattr(fn, "arguments", "{}"),
                        },
                    }
                )
            msg_dict["tool_calls"] = serialized
        choices_out.append({"message": msg_dict})
    body: dict[str, Any] = {"choices": choices_out}
    usage = getattr(response, "usage", None)
    if usage is not None:
        body["usage"] = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
            "prompt_cache_hit_tokens": getattr(usage, "prompt_cache_hit_tokens", 0) or 0,
            "prompt_cache_miss_tokens": getattr(usage, "prompt_cache_miss_tokens", 0) or 0,
        }
    return body


def _read_error_body(exc: APIStatusError) -> str:
    try:
        response = getattr(exc, "response", None)
        if response is not None:
            return getattr(response, "text", "") or ""
    except Exception:
        pass
    body = getattr(exc, "body", None)
    if isinstance(body, (bytes, bytearray)):
        return bytes(body).decode("utf-8", "replace")
    if isinstance(body, str):
        return body
    return ""


@dataclass
class LlmUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0


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
    """Manual context manager (avoiding @contextmanager typing issues with mypy strict).

    支持嵌套：内层 scope 退出时，其用量会合并到外层 scope，确保 API 层总量不丢失。
    """

    def __init__(self) -> None:
        self._usage = LlmUsage()
        self._token: Any = None
        self._parent: LlmUsage | None = None

    def __enter__(self) -> LlmUsage:
        self._parent = _USAGE_TRACKER.get()
        self._token = _USAGE_TRACKER.set(self._usage)
        return self._usage

    def __exit__(self, *args: object) -> None:
        if self._token is not None:
            _USAGE_TRACKER.reset(self._token)
            self._token = None
        # 将本 scope 的用量合并到父 scope，支持嵌套场景
        if self._parent is not None:
            self._parent.prompt_tokens += self._usage.prompt_tokens
            self._parent.completion_tokens += self._usage.completion_tokens
            self._parent.total_tokens += self._usage.total_tokens
            self._parent.prompt_cache_hit_tokens += self._usage.prompt_cache_hit_tokens
            self._parent.prompt_cache_miss_tokens += self._usage.prompt_cache_miss_tokens
            self._parent = None


def llm_usage_scope() -> _UsageScope:
    """Track token usage across multiple LLM calls in a single scope.

    Usage:
        with llm_usage_scope() as usage:
            reply = chat_completion(config, messages)
            print(usage.total_tokens)
    """
    return _UsageScope()


def apply_thinking_to_payload(
    payload: dict[str, Any],
    *,
    model: str,
    thinking: ThinkingState | None,
    reasoning_effort: ReasoningEffort | str | None = None,
) -> None:
    """Mutate payload with DeepSeek thinking controls when supported."""
    if thinking is None or not model_supports_thinking(model):
        return
    if thinking == "disabled":
        payload["thinking"] = {"type": "disabled"}
        return
    payload["thinking"] = {"type": "enabled"}
    if reasoning_effort in {"low", "high", "max"}:
        payload["reasoning_effort"] = reasoning_effort


def _with_strict_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    marked: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            marked.append(tool)
            continue
        fn = tool.get("function")
        if not isinstance(fn, dict):
            marked.append(tool)
            continue
        new_fn = dict(fn)
        new_fn["strict"] = True
        params = new_fn.get("parameters")
        if isinstance(params, dict):
            params = dict(params)
            params.setdefault("additionalProperties", False)
            new_fn["parameters"] = params
        marked.append({"type": "function", "function": new_fn})
    return marked


def chat_completion(
    config: LlmConfig,
    messages: list[dict[str, str]],
    *,
    timeout: float = 120.0,
    temperature: float = 0.7,
    on_delta: Callable[[str], None] | None = None,
    thinking: ThinkingState | None = "disabled",
    reasoning_effort: ReasoningEffort | str | None = None,
) -> str:
    if on_delta is None:
        return _chat_completion_once(
            config,
            messages,
            timeout=timeout,
            temperature=temperature,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
        )
    return chat_completion_stream(
        config,
        messages,
        on_delta=on_delta,
        timeout=timeout,
        temperature=temperature,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
    )


def chat_completion_stream(
    config: LlmConfig,
    messages: list[dict[str, str]],
    *,
    on_delta: Callable[[str], None],
    timeout: float = 120.0,
    temperature: float = 0.7,
    thinking: ThinkingState | None = "disabled",
    reasoning_effort: ReasoningEffort | str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    apply_thinking_to_payload(
        payload,
        model=config.model,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
    )
    last_error: str | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return _stream_request(config, payload, timeout, on_delta)
        except AgentError:
            # Empty-content stream (thinking mode on short inputs) — retry
            # with thinking disabled before giving up.
            if attempt >= _MAX_RETRIES:
                raise
            logger.warning("LLM stream empty content, retrying (attempt %d/%d)", attempt, _MAX_RETRIES)
            _sleep_for_retry(attempt)
            if thinking in ("enabled", "auto"):
                payload["thinking"] = {"type": "disabled"}
                if reasoning_effort is not None:
                    payload["reasoning_effort"] = None
            continue
        except (APIConnectionError, APITimeoutError) as exc:
            last_error = str(exc)
            logger.warning("LLM stream attempt %d/%d failed: %s", attempt, _MAX_RETRIES, exc)
            if attempt < _MAX_RETRIES:
                _sleep_for_retry(attempt)
        except APIStatusError as exc:
            detail = _read_error_body(exc)
            logger.warning("LLM stream HTTP error %s: %s", exc.status_code, detail[:300])
            if exc.status_code in _RETRYABLE_STATUSES and attempt < _MAX_RETRIES:
                _sleep_for_retry(attempt)
                continue
            message = _extract_api_error(detail) or f"大模型请求失败 ({exc.status_code})"
            raise AgentError(message) from exc
    raise AgentError(f"大模型流式请求失败（{_MAX_RETRIES} 次重试后）: {last_error or '未知错误'}")


def _stream_request(
    config: LlmConfig,
    payload: dict[str, Any],
    timeout: float,
    on_delta: Callable[[str], None],
) -> str:
    client = _build_openai_client(config, timeout)
    kwargs = _completion_kwargs(payload)
    kwargs["stream"] = True
    kwargs["stream_options"] = {"include_usage": True}
    parts: list[str] = []
    stream = client.chat.completions.create(**kwargs)
    for chunk in stream:
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            _record_usage(
                {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                    "prompt_cache_hit_tokens": getattr(usage, "prompt_cache_hit_tokens", 0) or 0,
                    "prompt_cache_miss_tokens": getattr(usage, "prompt_cache_miss_tokens", 0) or 0,
                }
            )
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        if delta is None:
            continue
        content = getattr(delta, "content", None)
        if isinstance(content, str) and content:
            parts.append(content)
            on_delta(content)
    result = "".join(parts).strip()
    if not result:
        raise AgentError("模型未返回任何内容（流式），请重试。若频繁出现，可在设置里关闭思考模式。")
    return result


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


def coerce_tool_choice_for_thinking(
    tool_choice: str | dict[str, Any],
    *,
    model: str,
    thinking: ThinkingState | None,
) -> str | dict[str, Any]:
    """DeepSeek V4 thinking mode rejects tool_choice=required / named function.

    Keep ``auto`` / ``none``; rewrite forced choices so native tools do not 400
    and fall back to leaking DSML/text tool markup into the chat UI.
    """
    if tool_choice in {"auto", "none"}:
        return tool_choice
    if not model_supports_thinking(model):
        return tool_choice
    if thinking == "disabled":
        return tool_choice
    return "auto"


def chat_completion_with_tools(
    config: LlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    tool_choice: str | dict[str, Any] = "auto",
    timeout: float = 120.0,
    temperature: float = 0.7,
    thinking: ThinkingState | None = "enabled",
    reasoning_effort: ReasoningEffort | str | None = "high",
    strict_tools: bool = False,
) -> ChatCompletionResult:
    """Call /chat/completions with OpenAI-style function tools."""
    active_tools = _with_strict_tools(tools) if strict_tools else tools
    effective_choice = coerce_tool_choice_for_thinking(
        tool_choice,
        model=config.model,
        thinking=thinking,
    )
    if effective_choice != tool_choice:
        logger.info(
            "Coerced tool_choice %r → %r for thinking-capable model %s",
            tool_choice,
            effective_choice,
            config.model,
        )
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
        "tools": active_tools,
        "tool_choice": effective_choice,
    }
    apply_thinking_to_payload(
        payload,
        model=config.model,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
    )
    base_url: str | None = None
    if strict_tools and model_supports_thinking(config.model):
        base_url = deepseek_beta_base_url(config.base_url).rstrip("/")
    last_error: str | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return _tools_request(config, payload, timeout, base_url)
        except (APIConnectionError, APITimeoutError) as exc:
            last_error = str(exc)
            logger.warning("LLM tools attempt %d/%d failed: %s", attempt, _MAX_RETRIES, exc)
            if attempt < _MAX_RETRIES:
                _sleep_for_retry(attempt)
        except APIStatusError as exc:
            detail = _read_error_body(exc)
            logger.warning("LLM tools HTTP error %s: %s", exc.status_code, detail[:300])
            if exc.status_code in _RETRYABLE_STATUSES and attempt < _MAX_RETRIES:
                _sleep_for_retry(attempt)
                continue
            message = _extract_api_error(detail) or f"大模型工具调用失败 ({exc.status_code})"
            raise AgentError(message) from exc
    raise AgentError(f"大模型工具调用失败（{_MAX_RETRIES} 次重试后）: {last_error or '未知错误'}")


def _tools_request(
    config: LlmConfig,
    payload: dict[str, Any],
    timeout: float,
    base_url: str | None,
) -> ChatCompletionResult:
    client = _build_openai_client(config, timeout, base_url=base_url)
    response = client.chat.completions.create(**_completion_kwargs(payload))
    body = _sdk_response_to_dict(response)
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


def _chat_completion_once(
    config: LlmConfig,
    messages: list[dict[str, str]],
    *,
    timeout: float,
    temperature: float,
    thinking: ThinkingState | None = "disabled",
    reasoning_effort: ReasoningEffort | str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
    }
    apply_thinking_to_payload(
        payload,
        model=config.model,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
    )
    last_error: str | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            body = _non_stream_request(config, payload, timeout)
        except (APIConnectionError, APITimeoutError) as exc:
            last_error = str(exc)
            logger.warning("LLM attempt %d/%d failed: %s", attempt, _MAX_RETRIES, exc)
            if attempt < _MAX_RETRIES:
                _sleep_for_retry(attempt)
            continue
        except APIStatusError as exc:
            detail = _read_error_body(exc)
            logger.warning("LLM HTTP error %s: %s", exc.status_code, detail[:300])
            if exc.status_code in _RETRYABLE_STATUSES and attempt < _MAX_RETRIES:
                _sleep_for_retry(attempt)
                continue
            message = _extract_api_error(detail) or f"大模型请求失败 ({exc.status_code})"
            raise AgentError(message) from exc

        _record_usage(body.get("usage"))
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise AgentError("大模型返回格式异常") from error
        content = _extract_message_text(message)
        if content:
            return content
        # Empty content — retry once more specifically. Empty replies are
        # common when thinking is enabled for short inputs, so fall back to
        # a non-thinking retry before giving up.
        if attempt < _MAX_RETRIES:
            logger.warning("LLM returned empty content, retrying (attempt %d/%d)", attempt, _MAX_RETRIES)
            _sleep_for_retry(attempt)
            if thinking in ("enabled", "auto"):
                payload["thinking"] = {"type": "disabled"}
                if reasoning_effort is not None:
                    payload["reasoning_effort"] = None
            continue
    if last_error:
        raise AgentError(f"大模型请求失败（{_MAX_RETRIES} 次重试后）: {last_error}")
    raise AgentError("模型未返回任何内容，请重试。若频繁出现，可在设置里关闭思考模式。")


def _non_stream_request(
    config: LlmConfig,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    client = _build_openai_client(config, timeout)
    response = client.chat.completions.create(**_completion_kwargs(payload))
    return _sdk_response_to_dict(response)


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
    tracker.prompt_cache_hit_tokens += _to_int(usage_payload.get("prompt_cache_hit_tokens"))
    tracker.prompt_cache_miss_tokens += _to_int(usage_payload.get("prompt_cache_miss_tokens"))


def _to_int(value: object) -> int:
    try:
        parsed = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0
