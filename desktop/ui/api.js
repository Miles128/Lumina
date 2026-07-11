class ApiTimeoutError extends Error {
  constructor(message) {
    super(message);
    this.name = "ApiTimeoutError";
  }
}

class ApiAbortError extends Error {
  constructor(message) {
    super(message);
    this.name = "ApiAbortError";
  }
}

async function apiRequest(method, route, body, requestOptions = {}) {
  const timeoutMs = Number(requestOptions.timeoutMs || 0);
  const externalSignal = requestOptions.signal || null;
  const controller = new AbortController();
  let timedOut = false;
  let timeoutId = null;
  let externalAbortListener = null;
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalAbortListener = () => controller.abort();
      externalSignal.addEventListener("abort", externalAbortListener, { once: true });
    }
  }
  if (timeoutMs > 0) {
    timeoutId = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
  }
  const fetchOptions = {
    method,
    signal: controller.signal,
  };
  if (body !== undefined && body !== null && !(body instanceof FormData)) {
    fetchOptions.headers = { "Content-Type": "application/json" };
    fetchOptions.body = JSON.stringify(body);
  } else if (body instanceof FormData) {
    fetchOptions.body = body;
  }
  let response;
  try {
    response = await fetch(route, fetchOptions);
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
    const text = await response.text();
    if (!response.ok) {
      throw new Error(text.trim() || `请求失败 (${response.status})`);
    }
    if (!text) {
      window.dispatchEvent(
        new CustomEvent("lumina:api-response", {
          detail: { method, route, requestBody: body || null, responseBody: null, responseText: "" },
        }),
      );
      return null;
    }
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch {
      throw new Error(text.trim().slice(0, 200) || "服务器返回了无效响应");
    }
    window.dispatchEvent(
      new CustomEvent("lumina:api-response", {
        detail: { method, route, requestBody: body || null, responseBody: parsed, responseText: text },
      }),
    );
    return parsed;
  } catch (error) {
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
    if (controller.signal.aborted) {
      if (timedOut) {
        throw new ApiTimeoutError("请求超时");
      }
      throw new ApiAbortError("请求已暂停");
    }
    throw error;
  } finally {
    // Always detach the external abort listener so it does not leak when the
    // request completes normally. { once: true } only fires on abort, not on
    // successful completion, so without this the listener would persist on
    // the external signal until it is garbage-collected.
    if (externalAbortListener && externalSignal) {
      externalSignal.removeEventListener("abort", externalAbortListener);
    }
  }
}

async function subscribeChatProgress(traceId, onEvent, signal) {
  if (!traceId) return;
  // SSE idle timeout: if no data arrives for SSE_IDLE_TIMEOUT_MS, abort the
  // connection so a silently-broken TCP link (backend crash, network black
  // hole) does not leave reader.read() blocking forever. The timer is reset
  // on every chunk; normal stream end clears it in finally.
  const SSE_IDLE_TIMEOUT_MS = 180_000;
  const controller = new AbortController();
  let sseTimeoutId = null;
  let timedOut = false;
  let externalAbortListener = null;
  if (signal) {
    if (signal.aborted) {
      controller.abort();
    } else {
      externalAbortListener = () => controller.abort();
      signal.addEventListener("abort", externalAbortListener, { once: true });
    }
  }
  const resetSseTimeout = () => {
    if (sseTimeoutId !== null) clearTimeout(sseTimeoutId);
    sseTimeoutId = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, SSE_IDLE_TIMEOUT_MS);
  };
  resetSseTimeout();
  try {
    const response = await fetch(`/api/chat/progress/${encodeURIComponent(traceId)}`, {
      signal: controller.signal,
      headers: { Accept: "text/event-stream" },
    });
    if (!response.ok || !response.body) {
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      // Any data received — reset the idle timer.
      resetSseTimeout();
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";
      for (const chunk of chunks) {
        const line = chunk.split("\n").find((row) => row.startsWith("data: "));
        if (!line) {
          continue;
        }
        try {
          onEvent(JSON.parse(line.slice(6)));
        } catch (_error) {
          // ignore malformed chunks
        }
      }
    }
  } catch (error) {
    // Swallow AbortError only when triggered by our own idle timeout.
    // External-signal aborts and other errors propagate to the caller.
    if (controller.signal.aborted && timedOut) {
      return;
    }
    throw error;
  } finally {
    if (sseTimeoutId !== null) clearTimeout(sseTimeoutId);
    if (externalAbortListener && signal) {
      signal.removeEventListener("abort", externalAbortListener);
    }
  }
}

window.SecretaryAPI = {
  request: apiRequest,
  subscribeChatProgress,
  ApiTimeoutError,
  ApiAbortError,
};
