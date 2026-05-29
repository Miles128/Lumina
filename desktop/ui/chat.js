(function () {
  "use strict";

  const welcome = document.getElementById("welcome");
  const messagesEl = document.getElementById("messages");
  const typingEl = document.getElementById("typing");
  const typingTextEl = document.getElementById("typing-text");
  const progressEl = document.getElementById("agent-progress");
  const progressListEl = document.getElementById("agent-progress-list");
  const pauseBtn = document.getElementById("btn-pause");
  const newThreadBtn = document.getElementById("btn-new-thread");
  const threadListEl = document.getElementById("thread-list");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const sendBtn = document.getElementById("btn-send");
  const mainScrollEl = document.querySelector(".chat-column .main");

  let busy = false;
  let pendingActionId = null;
  let activeRequestController = null;
  let typingTicker = null;
  let typingStartAt = 0;
  let slowNoticeSent = false;
  let threads = [];
  let currentThreadId = "";
  let streamingBubbleEl = null;
  let streamingText = "";

  const THREADS_KEY = "lumina.chat.threads.v1";
  const CURRENT_THREAD_KEY = "lumina.chat.current.v1";
  const RUNTIME_SUMMARY_RE =
    /^本次(?:回答|操作|同步|处理|确认)?(?:已返回结果|已执行)?[,，]?\s*耗时\s*[\d.]+\s*秒[。.]?$/;

  document.getElementById("btn-kb").addEventListener("click", openKnowledgeBase);
  document.getElementById("btn-sync").addEventListener("click", syncAll);

  document.querySelectorAll(".prompt, .suggestion").forEach((button) => {
    button.addEventListener("click", () => {
      sendMessage(button.dataset.prompt || "");
    });
  });

  chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(chatInput.value.trim());
  });

  chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      chatForm.requestSubmit();
    }
  });

  chatInput.addEventListener("input", autoResize);
  pauseBtn.addEventListener("click", pauseCurrentRequest);
  newThreadBtn.addEventListener("click", () => {
    createThread();
  });

  initThreads();

  function openKnowledgeBase() {
    window.secretary?.openKnowledge();
  }

  function autoResize() {
    chatInput.style.height = "auto";
    chatInput.style.height = `${Math.min(chatInput.scrollHeight, 160)}px`;
  }

  async function syncAll() {
    if (busy) return;
    appendMessage("user", "同步全部数据");
    setBusy(true);
    showTyping(true, "正在同步数据…");
    beginTypingTicker();
    try {
      const controller = createActiveController();
      const results = await window.SecretaryAPI.request("POST", "/api/sync", null, {
        signal: controller.signal,
        timeoutMs: 90_000,
      });
      const inserted = results.reduce((sum, item) => sum + item.inserted, 0);
      appendMessage("bot", `同步完成，写入 ${inserted} 条记忆。`);
    } catch (error) {
      handleRequestError(error, "同步");
    } finally {
      endTypingTicker();
      clearActiveController();
      showTyping(false);
      setBusy(false);
    }
  }

  async function sendMessage(text) {
    if (!text || busy) return;

    welcome.classList.add("hidden");
    appendMessage("user", text);
    chatInput.value = "";
    autoResize();
    setBusy(true);
    showTyping(true, "正在理解你的问题…");
    beginTypingTicker();
    slowNoticeSent = false;
    resetProgressLog();

    try {
      const controller = createActiveController();
      const traceId = createTraceId();
      void window.SecretaryAPI.subscribeChatProgress(traceId, handleProgressEvent, controller.signal);
      const response = await window.SecretaryAPI.request(
        "POST",
        "/api/chat",
        { message: text, trace_id: traceId },
        {
          signal: controller.signal,
          timeoutMs: 120_000,
        },
      );
      showTyping(false);

      if (response.needs_confirmation) {
        clearStreamingBubble();
        pendingActionId = response.confirmation_action_id;
        appendConfirmation(response);
      } else if (streamingBubbleEl) {
        finalizeStreamingMessage(response.reply);
      } else {
        appendMessage("bot", response.reply);
      }
    } catch (error) {
      clearStreamingBubble();
      handleRequestError(error, "回答");
    } finally {
      endTypingTicker();
      clearActiveController();
      showTyping(false);
      setBusy(false);
      chatInput.focus();
    }
  }

  async function handleConfirm(approved, options = {}) {
    if (!pendingActionId) return;
    const actionId = pendingActionId;
    pendingActionId = null;

    const confirmRow = document.querySelector(".confirmation-row");
    if (confirmRow) {
      const status = approved ? "✅ 已允许" : "❌ 已拒绝";
      confirmRow.querySelector(".confirm-actions").innerHTML = `<span class="confirm-status">${status}</span>`;
      confirmRow.classList.remove("confirmation-row");
    }

    setBusy(true);
    showTyping(true, "正在执行操作…");
    beginTypingTicker();

    try {
      const controller = createActiveController();
      const traceId = createTraceId();
      void window.SecretaryAPI.subscribeChatProgress(traceId, handleProgressEvent, controller.signal);
      const response = await window.SecretaryAPI.request(
        "POST",
        "/api/chat/confirm",
        {
          action_id: actionId,
          approved: approved,
          grant_permanent_read: Boolean(options.grantPermanentRead),
          grant_session_write: Boolean(options.grantSessionWrite),
          trace_id: traceId,
        },
        {
          signal: controller.signal,
          timeoutMs: 120_000,
        },
      );
      showTyping(false);

      if (response.needs_confirmation) {
        clearStreamingBubble();
        pendingActionId = response.confirmation_action_id;
        appendConfirmation(response);
      } else if (streamingBubbleEl) {
        finalizeStreamingMessage(response.reply);
      } else {
        appendMessage("bot", response.reply);
      }
    } catch (error) {
      clearStreamingBubble();
      handleRequestError(error, "操作");
    } finally {
      endTypingTicker();
      clearActiveController();
      showTyping(false);
      setBusy(false);
      chatInput.focus();
    }
  }

  function appendMessage(role, text) {
    appendMessageInternal(role, text, true);
  }

  function isRuntimeSummaryMessage(text) {
    const source = String(text || "").trim();
    if (!source) return false;
    return RUNTIME_SUMMARY_RE.test(source);
  }

  function appendMessageInternal(role, text, persist) {
    if (isRuntimeSummaryMessage(text)) {
      return;
    }
    const row = document.createElement("div");
    row.className = `message ${role}`;
    const avatarSrc = role === "bot" ? "/assets/avatar-bot.svg" : "/assets/avatar-user.svg";
    const bubbleClass = role === "bot" ? "bubble markdown" : "bubble";
    row.innerHTML =
      `<div class="avatar ${role}" aria-label="${role === "bot" ? "灵犀" : "你"}">` +
      `<img src="${avatarSrc}" alt="" aria-hidden="true" /></div>` +
      `<div class="${bubbleClass}">${renderMessageHtml(role, text)}</div>`;
    messagesEl.appendChild(row);
    scrollChatToBottom();
    if (persist) {
      persistMessage(role, text);
    }
  }

  function appendConfirmation(response) {
    const replyText = response.reply || "";
    const description = response.confirmation_description || "";
    const riskLevel = response.confirmation_risk_level || "";
    const kind = response.confirmation_kind || "";
    const row = document.createElement("div");
    row.className = "message bot confirmation-row";
    persistMessage("bot", replyText);

    const riskBadge = riskLevel === "high" ? '<span class="risk-badge risk-high">高风险</span>' :
                      riskLevel === "medium" ? '<span class="risk-badge risk-medium">中风险</span>' : '';

    let actions = `
      <button class="btn-confirm-primary" type="button" data-confirm="allow">执行</button>
      <button class="btn-confirm-deny" type="button" data-confirm="deny">拒绝</button>
    `;

    if (kind === "write_new") {
      actions = `
        <button class="btn-confirm-primary" type="button" data-confirm="once">仅本次执行</button>
        <button class="btn-confirm-secondary" type="button" data-confirm="session-write">本次授权（可新建文件）</button>
        <button class="btn-confirm-deny" type="button" data-confirm="deny">拒绝</button>
      `;
    }

    row.innerHTML = `
      <div class="bubble confirm-bubble">
        <div class="confirm-text markdown">${renderMarkdown(replyText)}</div>
        <div class="confirm-detail">${escapeHtml(description)}</div>
        ${riskBadge}
        <div class="confirm-actions">${actions}</div>
      </div>
    `;

    row.querySelectorAll("[data-confirm]").forEach((button) => {
      button.addEventListener("click", () => {
        const mode = button.dataset.confirm;
        if (mode === "deny") {
          handleConfirm(false);
          return;
        }
        if (mode === "session-write") {
          handleConfirm(true, { grantSessionWrite: true });
          return;
        }
        handleConfirm(true);
      });
    });

    messagesEl.appendChild(row);
    scrollChatToBottom();
  }

  window.__luminaConfirm = handleConfirm;

  function showTyping(visible, statusText = "正在处理…") {
    typingEl.hidden = !visible;
    if (typingTextEl) {
      typingTextEl.textContent = statusText;
    }
    if (visible) {
      scrollChatToBottom();
    }
  }

  function scrollChatToBottom() {
    if (!mainScrollEl) return;
    const scroll = () => {
      mainScrollEl.scrollTop = mainScrollEl.scrollHeight;
    };
    scroll();
    requestAnimationFrame(() => {
      scroll();
      requestAnimationFrame(scroll);
    });
  }

  function createTraceId() {
    if (window.crypto?.randomUUID) {
      return window.crypto.randomUUID();
    }
    return `trace-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function resetProgressLog() {
    if (!progressListEl) return;
    progressListEl.innerHTML = "";
    if (progressEl) {
      progressEl.hidden = true;
    }
  }

  function handleProgressEvent(event) {
    const kind = String(event?.kind || "");
    if (kind === "reply_start") {
      beginStreamingBubble();
    } else if (kind === "reply_delta" && event?.delta) {
      appendStreamingDelta(String(event.delta));
    } else if (kind === "reply_end") {
      // wait for POST to finalize
    }

    const label = String(event?.label || "").trim();
    if (!label && !kind.startsWith("reply_")) return;
    if (progressEl && progressListEl && label && !kind.startsWith("reply_")) {
      progressEl.hidden = false;
      const item = document.createElement("li");
      item.textContent = label;
      if (event?.kind === "tool_finished" && event.success === false) {
        item.className = "is-error";
      } else if (event?.kind === "done") {
        item.className = "is-done";
      }
      progressListEl.appendChild(item);
      progressListEl.scrollTop = progressListEl.scrollHeight;
      scrollChatToBottom();
    }
    if (event?.kind === "tool_started" || event?.kind === "iteration_started") {
      clearStreamingBubble();
      showTyping(true, label);
    }
    if (event?.kind === "done") {
      showTyping(true, "正在整理回复…");
    }
  }

  function beginStreamingBubble() {
    if (streamingBubbleEl) return;
    welcome.classList.add("hidden");
    streamingText = "";
    const row = document.createElement("div");
    row.className = "message bot streaming";
    row.innerHTML =
      `<div class="avatar bot" aria-label="灵犀">` +
      `<img src="/assets/avatar-bot.svg" alt="" aria-hidden="true" /></div>` +
      `<div class="bubble markdown"></div>`;
    messagesEl.appendChild(row);
    streamingBubbleEl = row.querySelector(".bubble");
    scrollChatToBottom();
  }

  function appendStreamingDelta(delta) {
    if (!streamingBubbleEl) {
      beginStreamingBubble();
    }
    streamingText += delta;
    streamingBubbleEl.innerHTML = renderMarkdown(streamingText);
    scrollChatToBottom();
  }

  function finalizeStreamingMessage(finalText) {
    if (!streamingBubbleEl) {
      appendMessage("bot", finalText);
      return;
    }
    streamingBubbleEl.innerHTML = renderMarkdown(finalText);
    persistMessage("bot", finalText);
    streamingBubbleEl = null;
    streamingText = "";
    scrollChatToBottom();
  }

  function clearStreamingBubble() {
    if (streamingBubbleEl) {
      streamingBubbleEl.closest(".message")?.remove();
    }
    streamingBubbleEl = null;
    streamingText = "";
  }

  function setBusy(value) {
    busy = value;
    sendBtn.disabled = value;
    chatInput.disabled = value;
    pauseBtn.hidden = !value;
  }

  function createActiveController() {
    const controller = new AbortController();
    activeRequestController = controller;
    return controller;
  }

  function clearActiveController() {
    activeRequestController = null;
  }

  function pauseCurrentRequest() {
    if (!activeRequestController) return;
    activeRequestController.abort();
  }

  function beginTypingTicker() {
    typingStartAt = Date.now();
    endTypingTicker();
    typingTicker = window.setInterval(() => {
      updateTypingStatus();
    }, 2500);
    updateTypingStatus();
  }

  function endTypingTicker() {
    if (typingTicker !== null) {
      clearInterval(typingTicker);
      typingTicker = null;
    }
  }

  function updateTypingStatus() {
    if (!busy) return;
    const elapsedSec = Math.floor((Date.now() - typingStartAt) / 1000);
    if (elapsedSec < 8) {
      showTyping(true, "正在理解你的问题…");
      return;
    }
    if (elapsedSec < 20) {
      showTyping(true, "正在整理相关信息…");
      return;
    }
    if (elapsedSec < 40) {
      showTyping(true, "正在调用工具处理…");
      return;
    }
    if (elapsedSec < 70) {
      showTyping(true, "还在继续处理，马上给你结果…");
      return;
    }
    showTyping(true, "这次耗时较长，你可以点「暂停」先中止。");
    if (!slowNoticeSent) {
      appendMessage("bot", "这次处理有点慢，我还在继续。你可以点「暂停」先停下。");
      slowNoticeSent = true;
    }
  }

  function handleRequestError(error, scene) {
    if (error instanceof window.SecretaryAPI.ApiAbortError) {
      appendMessage("bot", "已暂停这次请求。你可以继续发下一条。");
      return "已暂停";
    }
    if (error instanceof window.SecretaryAPI.ApiTimeoutError) {
      appendMessage(
        "bot",
        "这次等待超时，我还没拿到结果。你可以让我缩小范围后再试一次。",
      );
      return "超时";
    }
    appendMessage("bot", `${scene}失败：${error.message}`);
    return "失败";
  }

  function renderMessageHtml(role, text) {
    if (role !== "bot") {
      return escapeHtml(text).replaceAll("\n", "<br>");
    }
    return renderMarkdown(text);
  }

  function renderMarkdown(text) {
    const source = String(text || "");
    const codeBlocks = [];
    const placeholderPrefix = "__MD_CODE_BLOCK_";
    const fenced = source.replace(/```([\w-]+)?\n([\s\S]*?)```/g, (_all, lang, code) => {
      const langClass = lang ? ` class="lang-${escapeHtml(lang)}"` : "";
      const html = `<pre><code${langClass}>${escapeHtml(code.trimEnd())}</code></pre>`;
      const token = `${placeholderPrefix}${codeBlocks.length}__`;
      codeBlocks.push({ token, html });
      return token;
    });
    const escaped = escapeHtml(fenced);
    const lines = escaped.split("\n");
    const chunks = [];
    let inUl = false;
    let inOl = false;

    const closeLists = () => {
      if (inUl) {
        chunks.push("</ul>");
        inUl = false;
      }
      if (inOl) {
        chunks.push("</ol>");
        inOl = false;
      }
    };

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        closeLists();
        continue;
      }
      const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
      if (heading) {
        closeLists();
        const level = heading[1].length;
        chunks.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
        continue;
      }
      const ul = trimmed.match(/^[-*]\s+(.+)$/);
      if (ul) {
        if (inOl) {
          chunks.push("</ol>");
          inOl = false;
        }
        if (!inUl) {
          chunks.push("<ul>");
          inUl = true;
        }
        chunks.push(`<li>${renderInline(ul[1])}</li>`);
        continue;
      }
      const ol = trimmed.match(/^\d+\.\s+(.+)$/);
      if (ol) {
        if (inUl) {
          chunks.push("</ul>");
          inUl = false;
        }
        if (!inOl) {
          chunks.push("<ol>");
          inOl = true;
        }
        chunks.push(`<li>${renderInline(ol[1])}</li>`);
        continue;
      }
      const quote = trimmed.match(/^&gt;\s?(.+)$/);
      if (quote) {
        closeLists();
        chunks.push(`<blockquote>${renderInline(quote[1])}</blockquote>`);
        continue;
      }
      closeLists();
      chunks.push(`<p>${renderInline(trimmed)}</p>`);
    }
    closeLists();

    let html = chunks.join("");
    for (const block of codeBlocks) {
      html = html.replaceAll(block.token, block.html);
    }
    return html || `<p>${escapeHtml(source)}</p>`;
  }

  function renderInline(text) {
    return text
      .replace(/`([^`\n]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  function initThreads() {
    threads = sortThreadsByUpdatedAt(loadThreads());
    currentThreadId = "";
    threadListEl.addEventListener("click", (event) => {
      const button = event.target.closest("[data-thread-id]");
      if (!button) return;
      switchThread(button.dataset.threadId || "");
    });
    if (!threads.length) {
      createThread(false);
      return;
    }
    const savedThreadId = localStorage.getItem(CURRENT_THREAD_KEY) || "";
    currentThreadId = threads.some((item) => item.id === savedThreadId)
      ? savedThreadId
      : threads[0].id;
    renderThreadList();
    renderCurrentThreadMessages();
    scrollActiveThreadIntoView();
  }

  function createThread(clearBackend = true) {
    const thread = {
      id: `t_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
      title: "新对话",
      updatedAt: new Date().toISOString(),
      messages: [],
    };
    threads.unshift(thread);
    currentThreadId = thread.id;
    saveThreads();
    renderThreadList();
    renderCurrentThreadMessages();
    scrollActiveThreadIntoView();
    if (clearBackend) {
      resetBackendHistory();
    }
  }

  function switchThread(threadId) {
    if (!threadId || threadId === currentThreadId) return;
    currentThreadId = threadId;
    saveThreads();
    renderThreadList();
    renderCurrentThreadMessages();
    scrollActiveThreadIntoView();
    resetBackendHistory();
  }

  function scrollActiveThreadIntoView() {
    const active = threadListEl.querySelector(".thread-item.active");
    active?.scrollIntoView({ block: "nearest" });
  }

  function renderThreadList() {
    threadListEl.innerHTML = threads
      .map((item) => {
        const active = item.id === currentThreadId ? " active" : "";
        const preview = buildThreadPreview(item);
        return (
          `<button class="thread-item${active}" data-thread-id="${item.id}">` +
          `<div class="thread-item-title">${escapeHtml(item.title || "新对话")}</div>` +
          `<div class="thread-item-preview">${escapeHtml(preview)}</div>` +
          `<div class="thread-item-time">${formatThreadTime(item.updatedAt)}</div>` +
          `</button>`
        );
      })
      .join("");
  }

  function renderCurrentThreadMessages() {
    messagesEl.innerHTML = "";
    const thread = getCurrentThread();
    if (!thread || !Array.isArray(thread.messages) || thread.messages.length === 0) {
      welcome.classList.remove("hidden");
      return;
    }
    welcome.classList.add("hidden");
    for (const item of thread.messages) {
      appendMessageInternal(item.role, item.text, false);
    }
    scrollChatToBottom();
  }

  function persistMessage(role, text) {
    if (isRuntimeSummaryMessage(text)) {
      return;
    }
    const thread = getCurrentThread();
    if (!thread) return;
    thread.messages.push({
      role,
      text: String(text || ""),
      timestamp: new Date().toISOString(),
    });
    if (thread.messages.length > 400) {
      thread.messages = thread.messages.slice(-400);
    }
    if (role === "user" && (thread.title === "新对话" || !thread.title)) {
      thread.title = buildThreadTitle(text);
    }
    thread.updatedAt = new Date().toISOString();
    threads = sortThreadsByUpdatedAt(threads);
    saveThreads();
    renderThreadList();
  }

  function getCurrentThread() {
    return threads.find((item) => item.id === currentThreadId) || null;
  }

  function saveThreads() {
    localStorage.setItem(THREADS_KEY, JSON.stringify(threads));
    localStorage.setItem(CURRENT_THREAD_KEY, currentThreadId);
  }

  function loadThreads() {
    try {
      const raw = localStorage.getItem(THREADS_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      let changed = false;
      const valid = parsed
        .filter((item) => item && item.id && Array.isArray(item.messages))
        .map((item) => {
          const messages = item.messages.filter((msg) => !isRuntimeSummaryMessage(msg?.text));
          if (messages.length !== item.messages.length) {
            changed = true;
          }
          return { ...item, messages };
        });
      if (changed) {
        localStorage.setItem(THREADS_KEY, JSON.stringify(valid));
      }
      return sortThreadsByUpdatedAt(valid);
    } catch (_error) {
      return [];
    }
  }

  function buildThreadTitle(text) {
    const compact = String(text || "").replace(/\s+/g, " ").trim();
    if (!compact) return "新对话";
    return compact.length > 20 ? `${compact.slice(0, 20)}…` : compact;
  }

  function formatThreadTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const hh = String(date.getHours()).padStart(2, "0");
    const mm = String(date.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  }

  function buildThreadPreview(thread) {
    if (!thread || !Array.isArray(thread.messages) || thread.messages.length === 0) {
      return "暂无消息";
    }
    const last = thread.messages[thread.messages.length - 1];
    const text = String(last?.text || "").replace(/\s+/g, " ").trim();
    if (!text) return "暂无消息";
    return text.length > 24 ? `${text.slice(0, 24)}…` : text;
  }

  function sortThreadsByUpdatedAt(items) {
    return [...items].sort((a, b) => {
      const ta = Date.parse(a?.updatedAt || "") || 0;
      const tb = Date.parse(b?.updatedAt || "") || 0;
      return tb - ta;
    });
  }

  async function resetBackendHistory() {
    try {
      await window.SecretaryAPI.request("DELETE", "/api/chat/history", null, { timeoutMs: 20_000 });
    } catch (_error) {
      // Ignore reset errors, local thread UI remains usable.
    }
  }
})();
