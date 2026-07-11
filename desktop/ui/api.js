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
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener(
        "abort",
        () => {
          controller.abort();
        },
        { once: true },
      );
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
  } catch (error) {
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
    }
    if (controller.signal.aborted) {
      if (timedOut) {
        throw new ApiTimeoutError("请求超时");
      }
      throw new ApiAbortError("请求已暂停");
    }
    throw error;
  }
  if (timeoutId !== null) {
    clearTimeout(timeoutId);
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
}

async function subscribeChatProgress(traceId, onEvent, signal) {
  if (!traceId) return;
  const response = await fetch(`/api/chat/progress/${encodeURIComponent(traceId)}`, {
    signal,
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
}

window.SecretaryAPI = {
  request: apiRequest,
  subscribeChatProgress,
  ApiTimeoutError,
  ApiAbortError,
};
