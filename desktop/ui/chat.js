(function () {
  "use strict";

  const welcome = document.getElementById("welcome");
  const messagesEl = document.getElementById("messages");
  const typingEl = document.getElementById("typing");
  const typingTextEl = document.getElementById("typing-text");
  const progressEl = document.getElementById("agent-progress");
  const progressListEl = document.getElementById("agent-progress-list");
  const subagentTreeEl = document.getElementById("subagent-tree");
  const pauseBtn = document.getElementById("btn-pause");
  const newThreadBtn = document.getElementById("btn-new-thread");
  const threadListEl = document.getElementById("thread-list");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const sendBtn = document.getElementById("btn-send");
  const mainScrollEl = document.querySelector(".chat-column .main");
  const BOT_AVATAR_SRC = "/assets/logo.png?v=3";
  const agentModePicker = document.getElementById("agent-mode-picker");
  const agentModeBtn = document.getElementById("agent-mode-btn");
  const agentModeLabel = document.getElementById("agent-mode-label");
  const agentModeMenu = document.getElementById("agent-mode-menu");

  const AGENT_MODE_LABELS = {
    auto: "Auto",
    build: "Build",
    ask: "Ask",
    plan: "Plan",
    orchestrator: "Build",
  };
  let currentAgentMode = "auto";

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
  let progressSession = {
    bufferedItems: [],
    turnNodes: new Map(),
    turnRootId: "",
    hasTurnTree: false,
    maxIteration: 0,
    hasTools: false,
    hasSubagent: false,
    hasNetwork: false,
    hasThought: false,
    panelVisible: false,
  };

  const THREADS_KEY = "lumina.chat.threads.v1";
  const CURRENT_THREAD_KEY = "lumina.chat.current.v1";

  function t(key, vars) {
    if (window.LuminaI18n) {
      return window.LuminaI18n.t(key, vars);
    }
    return key;
  }

  function avatarLabel(role) {
    return role === "bot" ? t("bot.name") : t("user.me");
  }

  window.addEventListener("lumina:language", () => {
    document.querySelectorAll(".message .avatar").forEach((el) => {
      const isBot = el.classList.contains("bot");
      el.setAttribute("aria-label", avatarLabel(isBot ? "bot" : "user"));
    });
    window.LuminaI18n?.applyDocument();
  });
  const RUNTIME_SUMMARY_RE =
    /^本次(?:回答|操作|同步|处理|确认)?(?:已返回结果|已执行)?[,，]?\s*耗时\s*[\d.]+\s*秒[。.]?$/;

  document.getElementById("btn-kb").addEventListener("click", openKnowledgeBase);

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

  // Shortcut: Ctrl/Cmd+N to start a new thread (prevent browser default new window).
  window.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "n") {
      event.preventDefault();
      createThread();
      newThreadBtn.focus();
    }
  });

  // Agent mode picker: load current profile, bind toggle + selection.
  function setAgentModeMenuOpen(open) {
    if (!agentModeBtn || !agentModeMenu) return;
    agentModeBtn.setAttribute("aria-expanded", open ? "true" : "false");
    agentModeMenu.hidden = !open;
    agentModeMenu.querySelectorAll("li").forEach((li) => {
      li.classList.toggle("is-active", li.dataset.mode === currentAgentMode);
    });
  }

  function renderAgentModeLabel() {
    if (!agentModeLabel) return;
    agentModeLabel.textContent = AGENT_MODE_LABELS[currentAgentMode] || "Build";
  }

  async function switchAgentMode(mode) {
    if (mode === currentAgentMode) {
      setAgentModeMenuOpen(false);
      return;
    }
    const previous = currentAgentMode;
    currentAgentMode = mode;
    renderAgentModeLabel();
    setAgentModeMenuOpen(false);
    try {
      await window.SecretaryAPI.request("PUT", "/api/agent/config", { agent_profile: mode });
    } catch (error) {
      currentAgentMode = previous;
      renderAgentModeLabel();
      console.error("Failed to switch agent mode:", error);
    }
  }

  async function loadAgentMode() {
    if (!agentModeBtn) return;
    try {
      const config = await window.SecretaryAPI.request("GET", "/api/agent/config");
      const profile = String(config?.agent_profile || "auto").toLowerCase();
      const normalized = profile === "orchestrator" ? "build" : profile;
      if (AGENT_MODE_LABELS[normalized]) {
        currentAgentMode = normalized;
      }
    } catch (_error) {
      // Keep default "auto".
    }
    renderAgentModeLabel();
  }

  if (agentModeBtn && agentModeMenu) {
    agentModeBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      const open = agentModeBtn.getAttribute("aria-expanded") === "true";
      setAgentModeMenuOpen(!open);
    });
    agentModeMenu.addEventListener("click", (event) => {
      const li = event.target.closest("li[data-mode]");
      if (!li) return;
      void switchAgentMode(li.dataset.mode);
    });
    document.addEventListener("click", (event) => {
      if (!agentModePicker) return;
      if (agentModePicker.contains(event.target)) return;
      setAgentModeMenuOpen(false);
    });
    messagesEl.addEventListener("click", (event) => {
      const button = event.target.closest("[data-ask-answer]");
      if (!button || busy) return;
      event.preventDefault();
      void sendMessage(button.dataset.askAnswer || "");
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") setAgentModeMenuOpen(false);
    });
    void loadAgentMode();
  }

  const LUMINA_IDENTITY_INTRO_FALLBACK =
    "我是灵犀（Lumina），在你本机运行的个人 AI 秘书。\n\n" +
    "我的说话风格：轻巧灵动、简明扼要——先给结论，句子短，不铺垫。\n\n" +
    "我能帮你读本地文件、搜索记忆、联网搜索、同步数据源、调用工具；涉及写入或删除时会先征求你确认。\n\n" +
    "我的技术栈是：\n" +
    "- 前端：Electron + HTML / CSS / JavaScript\n" +
    "- 后端：Python + FastAPI\n" +
    "- 数据：本地 SQLite，配置与记忆存放在本机用户目录的 .lumina 文件夹";

  const LUMINA_AUTHOR_REPLY_FALLBACK =
    "灵犀（Lumina）由四海开发维护。\n\n" +
    "- 开发者：四海\n" +
    "- 邮箱：myx28@qq.com\n" +
    "- 版本：0.1.0\n\n" +
    "我是跑在你本机上的个人 AI 秘书；更多产品信息见右上角「关于」。";

  let cachedIdentityIntro = LUMINA_IDENTITY_INTRO_FALLBACK;
  let cachedAuthorReply = LUMINA_AUTHOR_REPLY_FALLBACK;

  void initThreads();
  void prefetchIdentityIntro();
  void prefetchAuthorReply();

  function openKnowledgeBase() {
    window.secretary?.openKnowledge();
  }

  function autoResize() {
    chatInput.style.height = "auto";
    chatInput.style.height = `${Math.min(chatInput.scrollHeight, 160)}px`;
  }

  async function prefetchIdentityIntro() {
    try {
      const data = await window.SecretaryAPI.request("GET", "/api/identity/intro", null, {
        timeoutMs: 5000,
      });
      if (data?.reply) {
        cachedIdentityIntro = String(data.reply);
      }
    } catch (_error) {
      // Keep bundled fallback intro.
    }
  }

  async function prefetchAuthorReply() {
    try {
      const data = await window.SecretaryAPI.request("GET", "/api/identity/author", null, {
        timeoutMs: 5000,
      });
      if (data?.reply) {
        cachedAuthorReply = String(data.reply);
      }
    } catch (_error) {
      // Keep bundled fallback author reply.
    }
  }

  function sendAuthorReply(userText) {
    welcome.classList.add("hidden");
    appendMessage("user", userText);
    chatInput.value = "";
    autoResize();
    resetProgressLog();
    showTyping(false);
    endTypingTicker();
    appendMessage("bot", cachedAuthorReply);
    scrollChatToBottom();
    void window.SecretaryAPI.request(
      "POST",
      "/api/chat",
      { message: userText, trace_id: "", thread_id: currentThreadId || "" },
      { timeoutMs: 15_000 },
    )
      .then(() => syncThreadsFromServer({ render: false }))
      .catch(() => {});
  }

  function sendIdentityIntro(userText) {
    welcome.classList.add("hidden");
    appendMessage("user", userText);
    chatInput.value = "";
    autoResize();
    resetProgressLog();
    showTyping(false);
    endTypingTicker();
    appendMessage("bot", cachedIdentityIntro);
    scrollChatToBottom();
    void window.SecretaryAPI.request(
      "POST",
      "/api/chat",
      { message: userText, trace_id: "", thread_id: currentThreadId || "" },
      { timeoutMs: 15_000 },
    )
      .then(() => syncThreadsFromServer({ render: false }))
      .catch(() => {
        // History sync is best-effort; intro is already on screen.
      });
  }

  async function sendMessage(text) {
    if (!text) return;

    // Author / identity routing is handled only by the backend (PromptGate + fast paths).
    // Client-side shortcuts caused false positives (e.g. "open design 的作者").

    if (busy) return;

    welcome.classList.add("hidden");
    appendMessage("user", text);
    chatInput.value = "";
    autoResize();
    setBusy(true);
    slowNoticeSent = false;
    resetProgressLog();
    showTyping(true, t("chat.typing.understand"));
    beginTypingTicker();

    try {
      const controller = createActiveController();
      const traceId = createTraceId();
      void window.SecretaryAPI.subscribeChatProgress(traceId, handleProgressEvent, controller.signal);
      const chatBody = { message: text, trace_id: traceId, thread_id: currentThreadId || "" };
      const response = await window.SecretaryAPI.request(
        "POST",
        "/api/chat",
        chatBody,
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
        appendGroundingMeta(response);
      } else {
        appendMessage("bot", response.reply);
        appendGroundingMeta(response);
      }
      void syncThreadsFromServer({ render: false });
    } catch (error) {
      clearStreamingBubble();
      handleRequestError(error, t("chat.error.reply"));
    } finally {
      finalizeProgressSession();
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
      const status = approved ? `✅ ${t("confirm.allow")}` : `❌ ${t("confirm.deny")}`;
      confirmRow.querySelector(".confirm-actions").innerHTML = `<span class="confirm-status">${status}</span>`;
      confirmRow.classList.remove("confirmation-row");
    }

    setBusy(true);
    showTyping(true, t("chat.typing.execute"));
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
          thread_id: currentThreadId || "",
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
        appendGroundingMeta(response);
      } else {
        appendMessage("bot", response.reply);
        appendGroundingMeta(response);
      }
      void syncThreadsFromServer({ render: false });
    } catch (error) {
      clearStreamingBubble();
      handleRequestError(error, t("chat.error.action"));
    } finally {
      finalizeProgressSession();
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

  function usesGroundingTools(response) {
    const tools = Array.isArray(response?.used_tools) ? response.used_tools : [];
    return tools.some(
      (name) =>
        /^(list_dir|file_read|search_files|search_memory|session_search|shibei_search|shibei_list_sources)$/.test(name) ||
        /^mcp_.*(read|list|file|directory|search)/i.test(name),
    );
  }

  function usesFileTools(response) {
    return usesGroundingTools(response);
  }

  const REPLY_PATH_PATTERNS = [
    /(?:~\/|\/Users\/|\.\/|\.\.\/)[^\s"'`<>]+/,
    /\b[\w./-]+\.(?:py|js|ts|tsx|jsx|json|md|yaml|yml|toml|txt|csv)\b/i,
    /`[^`]+\.(?:py|js|ts|md|json|yaml|yml|toml|txt)`/,
  ];

  function replyMentionsPaths(text) {
    const source = String(text || "").trim();
    if (!source) return false;
    return REPLY_PATH_PATTERNS.some((pattern) => pattern.test(source));
  }

  function replySimulatesFileListing(text) {
    const source = String(text || "");
    if (!source.trim()) return false;
    if (/^\s*\$\s*ls\b/m.test(source)) return true;
    if (/^total\s+\d+/m.test(source)) return true;
    if (/^[-drwxl]{10}\s+\d+\s+/m.test(source)) return true;
    const treeLines = source.split("\n").filter((line) => /^[├└│──]/.test(line.trim())).length;
    if (treeLines >= 2) return true;
    const mdMatches = source.match(/[\w.-]+\.md\b/gi) || [];
    if (mdMatches.length >= 3 && (treeLines >= 1 || source.includes("├──"))) return true;
    if (mdMatches.length >= 5) return true;
    return false;
  }

  function isOfflineOrSetupReply(response) {
    if (!response || response.used_llm !== false) return false;
    const reply = String(response.reply || "");
    return (
      /离线模式/.test(reply) ||
      /还没配置大模型/.test(reply) ||
      /无法连接大模型/.test(reply)
    );
  }

  function groundingUnverifiedReason(response) {
    if (!response) return "";
    if (isOfflineOrSetupReply(response)) return "";
    if (response.grounding_note) return response.grounding_note;
    const reply = String(response.reply || "");
    if (replySimulatesFileListing(reply) && !usesFileTools(response)) {
      return t("chat.grounding.unverifiedSimulated");
    }
    if (replyMentionsPaths(reply) && !usesFileTools(response)) {
      return t("chat.grounding.unverifiedNoTools");
    }
    if (response.grounding_verified === false) {
      return t("chat.grounding.unverifiedMismatch");
    }
    return "";
  }

  function shouldShowGroundingUnverified(response) {
    if (!response) return false;
    if (isOfflineOrSetupReply(response)) return false;
    if (response.grounding_verified === false) return true;
    const reply = String(response.reply || "");
    if (replySimulatesFileListing(reply) && !usesFileTools(response)) return true;
    return replyMentionsPaths(reply) && !usesFileTools(response);
  }

  function appendGroundingMeta(response) {
    if (!response) return;
    const showUnverified = shouldShowGroundingUnverified(response);
    const showVerified =
      !showUnverified && usesGroundingTools(response) && response.grounding_verified !== false;
    if (!showVerified && !showUnverified) return;

    const rows = messagesEl.querySelectorAll(".message.bot");
    const row = rows[rows.length - 1];
    if (!row || row.querySelector(".message-grounding-meta")) return;

    const bubble = row.querySelector(".bubble");
    if (!bubble) return;

    const meta = document.createElement("div");
    meta.className = "message-grounding-meta";
    if (showUnverified) {
      meta.classList.add("is-unverified");
      const reason = groundingUnverifiedReason(response);
      meta.textContent = reason ? `${t("chat.grounding.unverified")} · ${reason}` : t("chat.grounding.unverified");
    } else {
      meta.classList.add("is-verified");
      const count = Array.isArray(response.files_read) ? response.files_read.length : 0;
      meta.textContent = count
        ? `${t("chat.grounding.verified")} · ${count} files`
        : t("chat.grounding.verified");
    }
    bubble.appendChild(meta);
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
    const avatarSrc = role === "bot" ? BOT_AVATAR_SRC : "/assets/avatar-user.svg";
    const bubbleClass = "bubble markdown";
    row.innerHTML =
      `<div class="avatar ${role}" aria-label="${avatarLabel(role)}">` +
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
    const scopeBadge = response.confirmation_scope === "subagent"
      ? `<span class="scope-badge scope-subagent">${escapeHtml(t("chat.confirm.subagent"))}</span>`
      : "";

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
      <div class="avatar bot" aria-label="${avatarLabel("bot")}">
        <img src="${BOT_AVATAR_SRC}" alt="" aria-hidden="true" />
      </div>
      <div class="bubble confirm-bubble">
        <div class="confirm-text markdown">${renderMarkdown(replyText)}</div>
        <div class="confirm-detail">${escapeHtml(description)}</div>
        ${scopeBadge}
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

  function showTyping(visible, statusText = t("chat.processing")) {
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

  const IDENTITY_INTRO_SNIPPET = "我是灵犀（Lumina）";

  function normalizeIdentityText(text) {
    return String(text || "").trim().replace(/[？?!！。.]+$/g, "");
  }

  function isThirdPartyProjectAuthorQuestion(text) {
    const t = normalizeIdentityText(text);
    if (!t) return false;
    if (/你|灵犀|本助手|这个助手/.test(t)) return false;
    if (
      /^([A-Za-z0-9][\w./\s-]{1,48}?)\s*(?:项目|仓库|repo)?\s*的?\s*(作者|开发者|创建者|维护者|谁写|谁开发)/i.test(
        t,
      )
    ) {
      return true;
    }
    if (
      /(?:找|查|看|请问|帮我).{0,16}?[A-Za-z0-9][\w./\s-]{1,48}?\s*(?:项目|仓库|repo)?\s*的?\s*(作者|开发者|创建者|维护者|谁写|谁开发)/i.test(
        t,
      )
    ) {
      return true;
    }
    if (/\bopen\s*[-_]?\s*design\b/i.test(t) && /(作者|开发者|创建者|维护者|谁写|谁开发)/.test(t)) {
      return true;
    }
    if (/(~|\/Users\/|\/)/.test(t) && /(作者|开发者|创建者|维护者|谁写|谁开发)/.test(t)) {
      return true;
    }
    return false;
  }

  function isAuthorRequest(text) {
    const t = normalizeIdentityText(text);
    if (!t) return false;
    if (isThirdPartyProjectAuthorQuestion(t)) return false;
    if (
      /谁写的|谁写|谁开发|谁做的|谁制作|谁创造|你的作者|你的开发者|你的创建者|谁是你的作者|谁是你的开发者|你的作者是谁|你的开发者是谁|谁创造了你|谁创造了灵犀|who made you|who created you|who built you|who developed you/i.test(
        t,
      )
    ) {
      return true;
    }
    if (/谁.{0,6}写.{0,4}(你|灵犀|lumina)/i.test(t)) return true;
    if (/(你|灵犀).{0,8}(作者|开发者|创建者|制作人)/i.test(t)) return true;
    if (
      /^(作者|开发者|创建者|制作人)(是谁|哪位|谁)[啊呀吗]?[？?]?$/i.test(t) ||
      /谁(开发|做|写|创造)了?(你|灵犀)/i.test(t)
    ) {
      return true;
    }
    return false;
  }

  function coreIdentityMatch(text) {
    const t = normalizeIdentityText(text);
    if (!t) return false;
    if (isAuthorRequest(t)) return false;
    if (/帮我写|帮我做|帮我撰|帮我起草|帮我编辑|帮我润色|写一份|写个|撰写|起草/.test(t)) {
      return false;
    }
    if (/我的/.test(t) && /自我介绍/.test(t) && !/你/.test(t)) return false;
    if (/自我介绍/.test(t)) return true;
    if (/^(介绍一下|介绍下|介绍)$/.test(t)) return true;
    if (t === "你是谁" || t === "你是什么" || /^你是谁[啊呀吗]?[？?]?$/.test(t)) return true;
    if (
      /你是什么|介绍一下你|介绍一下灵犀|说说你自己|你叫什么|你叫啥|你是做什么|你是干啥|你能做什么|你会什么|你都能干什么|你会干什么|说说你的能力|你有什么功能|什么是灵犀|灵犀是什么|who are you|what are you|what is lumina/i.test(
        t,
      )
    ) {
      return true;
    }
    if (/(做|来|请|给).{0,4}自我介绍/.test(t)) return true;
    if (/介绍(一下)?(你|你自己|灵犀|lumina)/i.test(t)) return true;
    if (/(你|灵犀).{0,6}介绍/i.test(t)) return true;
    if (/再.{0,8}介绍.{0,8}(你|自己|灵犀)?/.test(t)) return true;
    return false;
  }

  function isIdentityRepeatRequest(text, messages) {
    const t = normalizeIdentityText(text);
    if (!/再说一遍|再说一次|再来一遍|再来一次|再讲一遍|重复一遍|再介绍/.test(t)) {
      return false;
    }
    if (/(你|自己|灵犀|介绍|是谁|做什么|能力|功能)/.test(t)) return true;
    if (!Array.isArray(messages) || !messages.length) return false;
    for (let i = messages.length - 1; i >= 0 && i >= messages.length - 6; i -= 1) {
      const item = messages[i];
      if (!item) continue;
      if (item.role === "bot" && String(item.text || "").includes(IDENTITY_INTRO_SNIPPET)) {
        return true;
      }
      if (item.role === "user" && coreIdentityMatch(item.text || "")) {
        return true;
      }
    }
    return false;
  }

  function isIdentityRequest(text) {
    if (coreIdentityMatch(text)) return true;
    return isIdentityRepeatRequest(text, getCurrentThread()?.messages || []);
  }

  function resetTransientUI() {
    resetProgressLog();
    clearStreamingBubble();
    showTyping(false);
    endTypingTicker();
    pendingActionId = null;
  }

  function resetProgressLog() {
    progressSession = {
      bufferedItems: [],
      turnNodes: new Map(),
      turnRootId: "",
      hasTurnTree: false,
      maxIteration: 0,
      hasTools: false,
      hasSubagent: false,
      hasNetwork: false,
      hasThought: false,
      panelVisible: false,
    };
    if (subagentTreeEl) {
      subagentTreeEl.hidden = true;
      subagentTreeEl.innerHTML = "";
    }
    if (!progressListEl) return;
    progressListEl.hidden = false;
    progressListEl.innerHTML = "";
    if (progressEl) {
      progressEl.hidden = true;
    }
  }

  function shouldShowProgressPanel() {
    return (
      progressSession.maxIteration > 0 ||
      progressSession.hasTools ||
      progressSession.hasNetwork ||
      progressSession.hasSubagent ||
      progressSession.hasThought ||
      progressSession.hasTurnTree
    );
  }

  function normalizeTurnStatus(event) {
    const kind = String(event?.kind || "");
    if (kind === "pause_confirmation" || kind === "subagent_paused") return "paused";
    if (kind === "turn_completed") return event?.success === false ? "paused" : "done";
    if (kind.endsWith("_finished") || kind === "tool_finished" || kind === "iteration_completed") {
      return event?.success === false ? "failed" : "done";
    }
    if (kind === "stopped") return "failed";
    return "running";
  }

  function turnNodeType(event) {
    const kind = String(event?.kind || "");
    if (kind.startsWith("turn_")) return "turn";
    if (kind.startsWith("subagent_")) return "subagent";
    if (kind.startsWith("cli_agent_")) return "cli";
    if (kind === "pause_confirmation") return "pause";
    if (kind.startsWith("tool_")) return "tool";
    if (kind.startsWith("iteration_")) return "iteration";
    return "event";
  }

  function turnNodeId(event) {
    const kind = String(event?.kind || "");
    const turnId = String(event?.turn_id || "turn_local").trim();
    const subRunId = String(event?.sub_run_id || "").trim();
    const toolName = String(event?.tool_name || "").trim();
    const iteration = Number(event?.iteration) || 0;
    if (kind.startsWith("turn_")) return turnId;
    if (kind.startsWith("subagent_")) return `sub:${subRunId || turnId}`;
    if (kind.startsWith("cli_agent_")) return `cli:${subRunId || turnId}`;
    if (kind === "pause_confirmation") return `pause:${turnId}:${toolName || "confirm"}`;
    if (kind.startsWith("tool_")) {
      const parent = subRunId ? `sub:${subRunId}` : turnId;
      return `${parent}:tool:${toolName || "tool"}:${iteration}`;
    }
    if (kind.startsWith("iteration_")) return `${turnId}:iteration:${iteration}`;
    return String(event?.item_id || `${turnId}:${kind}:${Date.now()}`);
  }

  function turnParentId(event) {
    const kind = String(event?.kind || "");
    const turnId = String(event?.turn_id || progressSession.turnRootId || "turn_local").trim();
    const subRunId = String(event?.sub_run_id || "").trim();
    if (kind.startsWith("turn_")) return "";
    if (kind.startsWith("tool_") && subRunId) return `sub:${subRunId}`;
    if (kind.startsWith("cli_agent_")) return "";
    if (kind.startsWith("subagent_")) {
      const parentSubRunId = String(event?.parent_sub_run_id || "").trim();
      return parentSubRunId ? `sub:${parentSubRunId}` : turnId;
    }
    return turnId;
  }

  function fallbackTurnNode(parentId) {
    return {
      id: parentId,
      parentId: "",
      type: "turn",
      label: t("chat.turn.root"),
      detail: "",
      status: "running",
      children: [],
      order: progressSession.turnNodes.size,
    };
  }

  function upsertTurnTreeNode(event, label) {
    const kind = String(event?.kind || "");
    if (kind.startsWith("reply_")) return;
    const id = turnNodeId(event);
    const parentId = turnParentId(event);
    progressSession.hasTurnTree = true;
    if (kind === "turn_started" || (!progressSession.turnRootId && parentId === "")) {
      progressSession.turnRootId = id;
    }
    if (parentId && !progressSession.turnNodes.has(parentId)) {
      progressSession.turnNodes.set(parentId, fallbackTurnNode(parentId));
    }
    const existing = progressSession.turnNodes.get(id) || {
      id,
      parentId,
      type: turnNodeType(event),
      label: "",
      detail: "",
      status: "running",
      children: [],
      order: progressSession.turnNodes.size,
    };
    existing.parentId = existing.parentId || parentId;
    existing.type = turnNodeType(event);
    existing.label = label || existing.label || kind;
    existing.status = normalizeTurnStatus(event);
    if (event?.detail) existing.detail = String(event.detail);
    if (event?.goal && !existing.detail) existing.detail = String(event.goal);
    if (event?.message && existing.type === "turn" && !existing.detail) {
      existing.detail = String(event.message);
    }
    progressSession.turnNodes.set(id, existing);
    if (parentId) {
      const parent = progressSession.turnNodes.get(parentId) || fallbackTurnNode(parentId);
      if (!parent.children.includes(id)) {
        parent.children.push(id);
      }
      progressSession.turnNodes.set(parentId, parent);
    }
    renderTurnTree();
  }

  function renderTurnTreeNode(nodeId, depth = 0) {
    const node = progressSession.turnNodes.get(nodeId);
    if (!node) return "";
    const children = node.children
      .map((childId) => progressSession.turnNodes.get(childId))
      .filter(Boolean)
      .sort((a, b) => a.order - b.order)
      .map((child) => renderTurnTreeNode(child.id, depth + 1))
      .join("");
    const detail = node.detail
      ? `<div class="turn-tree-detail markdown">${renderMarkdown(node.detail)}</div>`
      : "";
    const childrenHtml = children ? `<ul class="turn-tree-children">${children}</ul>` : "";
    return (
      `<li class="turn-tree-node depth-${depth} is-${escapeAttr(node.status)}">` +
      `<div class="turn-tree-line">${escapeHtml(node.label)}</div>` +
      detail +
      childrenHtml +
      `</li>`
    );
  }

  function renderTurnTree() {
    if (!subagentTreeEl) return;
    if (!progressSession.hasTurnTree || progressSession.turnNodes.size === 0) {
      subagentTreeEl.hidden = true;
      subagentTreeEl.innerHTML = "";
      return;
    }
    subagentTreeEl.hidden = false;
    subagentTreeEl.classList.add("turn-tree");
    const rootId = progressSession.turnRootId || [...progressSession.turnNodes.keys()][0];
    subagentTreeEl.innerHTML = `<ul class="turn-tree-root">${renderTurnTreeNode(rootId, 0)}</ul>`;
  }

  function isSubagentProgressEvent(event) {
    const kind = String(event?.kind || "");
    return (
      kind === "subagent_started" ||
      kind === "subagent_finished" ||
      Boolean(event?.sub_run_id)
    );
  }

  function createProgressDetailElement(detail) {
    const detailEl = document.createElement("div");
    detailEl.className = "progress-detail markdown";
    detailEl.innerHTML = renderMarkdown(detail);
    return detailEl;
  }

  function createProgressListItem(event, label) {
    const item = document.createElement("li");
    const labelEl = document.createElement("div");
    labelEl.className = "progress-label";
    labelEl.textContent = label;
    item.appendChild(labelEl);
    const detail = String(event?.detail || "").trim();
    if (detail) {
      item.appendChild(createProgressDetailElement(detail));
    }
    const kind = String(event?.kind || "");
    if (isSubagentProgressEvent(event)) {
      item.classList.add("is-subagent");
    }
    const toolName = String(event?.tool_name || "");
    if (
      (kind === "tool_started" || kind === "tool_finished") &&
      (toolName === "web_search" ||
        toolName === "web_fetch" ||
        toolName.startsWith("browser_"))
    ) {
      item.classList.add("is-network");
    }
    if (kind === "iteration_started" && /网络连接/.test(label)) {
      item.classList.add("is-network");
    }
    if (kind === "tool_finished" && event.success === false) {
      item.classList.add("is-error");
    } else if (kind === "iteration_completed" || kind === "done") {
      item.classList.add("is-done");
    }
    return item;
  }

  function flushProgressPanel() {
    if (!progressEl || !progressListEl || progressSession.panelVisible) return;
    if (!shouldShowProgressPanel()) return;
    progressSession.panelVisible = true;
    progressEl.hidden = false;
    progressListEl.innerHTML = "";
    if (progressSession.hasTurnTree) {
      renderTurnTree();
      progressListEl.hidden = true;
    } else {
      progressListEl.hidden = false;
      for (const item of progressSession.bufferedItems) {
        progressListEl.appendChild(item);
      }
      progressListEl.scrollTop = progressListEl.scrollHeight;
    }
  }

  function appendProgressItem(event, label) {
    const kind = String(event?.kind || "");
    if (kind === "iteration_started") {
      progressSession.maxIteration = Math.max(
        progressSession.maxIteration,
        Number(event.iteration) || 0,
      );
    }
    if (
      kind === "tool_started" ||
      kind === "tool_finished" ||
      kind === "subagent_started" ||
      kind === "subagent_finished" ||
      kind === "cli_agent_started" ||
      kind === "cli_agent_finished"
    ) {
      progressSession.hasTools = true;
    }
    const toolName = String(event?.tool_name || "");
    if (
      (kind === "tool_started" || kind === "tool_finished") &&
      (toolName === "web_search" ||
        toolName === "web_fetch" ||
        toolName.startsWith("browser_"))
    ) {
      progressSession.hasNetwork = true;
    }
    if (kind === "iteration_started" && /网络连接/.test(String(event?.message || label))) {
      progressSession.hasNetwork = true;
    }
    if (kind === "subagent_started" || kind === "subagent_finished" || event?.sub_run_id) {
      progressSession.hasSubagent = true;
    }
    if (Number(event?.schema_version || 0) >= 2 || event?.turn_id || event?.sub_run_id) {
      upsertTurnTreeNode(event, label);
      if (shouldShowProgressPanel()) {
        if (!progressSession.panelVisible) {
          flushProgressPanel();
        } else {
          progressEl.hidden = false;
          progressListEl.hidden = true;
          renderTurnTree();
        }
      }
      return;
    }
    const item = createProgressListItem(event, label);
    progressSession.bufferedItems.push(item);
    if (shouldShowProgressPanel()) {
      if (!progressSession.panelVisible) {
        flushProgressPanel();
      } else {
        progressEl.hidden = false;
        progressListEl.appendChild(item);
        progressListEl.scrollTop = progressListEl.scrollHeight;
      }
    }
  }

  function finalizeProgressSession() {
    if (!shouldShowProgressPanel()) {
      resetProgressLog();
      return;
    }
    flushProgressPanel();
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
      appendProgressItem(event, label);
      scrollChatToBottom();
    }
    if (
      kind === "subagent_started" ||
      (kind === "tool_started" && event?.tool_name === "spawn_subagent")
    ) {
      clearStreamingBubble({ saveToProgress: true });
      showTyping(true, label || t("chat.typing.subagent"));
    } else if (kind === "subagent_paused") {
      showTyping(true, label || t("chat.subagent.paused"));
    } else if (kind === "subagent_finished") {
      showTyping(true, t("chat.typing.organize"));
    } else if (
      kind === "tool_started" ||
      kind === "iteration_started" ||
      kind === "iteration_completed"
    ) {
      clearStreamingBubble({ saveToProgress: true });
      showTyping(true, label);
    }
    if (event?.kind === "done" && shouldShowProgressPanel()) {
      showTyping(true, t("chat.typing.organize"));
    }
  }

  function beginStreamingBubble() {
    if (streamingBubbleEl) return;
    welcome.classList.add("hidden");
    streamingText = "";
    const row = document.createElement("div");
    row.className = "message bot streaming";
    row.innerHTML =
      `<div class="avatar bot" aria-label="${avatarLabel("bot")}">` +
      `<img src="${BOT_AVATAR_SRC}" alt="" aria-hidden="true" /></div>` +
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

  function flushStreamingToProgress() {
    const text = streamingText.trim();
    if (!text) return;
    progressSession.hasThought = true;
    appendProgressItem({ kind: "thought", detail: text }, t("chat.progress.thought"));
  }

  function clearStreamingBubble(options = {}) {
    if (options.saveToProgress) {
      flushStreamingToProgress();
    }
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
    activeRequestController = null;
    setBusy(false);
    showTyping(false);
    endTypingTicker();
    clearStreamingBubble();
    finalizeProgressSession();
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
    const hasAgentActivity =
      progressSession.maxIteration > 0 ||
      progressSession.hasTools ||
      progressSession.hasSubagent;

    if (!hasAgentActivity) {
      if (elapsedSec < 15) {
        showTyping(true, t("chat.typing.understand"));
        return;
      }
      if (elapsedSec < 45) {
        showTyping(true, t("chat.typing.almost"));
        return;
      }
      showTyping(true, t("chat.typing.slow"));
      if (!slowNoticeSent) {
        appendMessage("bot", t("chat.slowNotice"));
        slowNoticeSent = true;
      }
      return;
    }

    if (elapsedSec < 8) {
      showTyping(true, t("chat.typing.understand"));
      return;
    }
    if (elapsedSec < 20) {
      showTyping(true, t("chat.typing.gather"));
      return;
    }
    if (elapsedSec < 40) {
      showTyping(true, t("chat.typing.tools"));
      return;
    }
    if (elapsedSec < 70) {
      showTyping(true, t("chat.typing.almost"));
      return;
    }
    showTyping(true, t("chat.typing.slow"));
    if (!slowNoticeSent) {
      appendMessage("bot", t("chat.slowNotice"));
      slowNoticeSent = true;
    }
  }

  function handleRequestError(error, scene) {
    if (error instanceof window.SecretaryAPI.ApiAbortError) {
      appendMessage("bot", t("chat.paused"));
      return "已暂停";
    }
    if (error instanceof window.SecretaryAPI.ApiTimeoutError) {
      appendMessage("bot", t("chat.timeout"));
      return "超时";
    }
    appendMessage("bot", `${scene}: ${error.message}`);
    return "error";
  }

  function renderMessageHtml(role, text) {
    if (role === "bot") {
      const askHtml = renderAskUserHtml(text);
      if (askHtml) return askHtml;
    }
    return renderMarkdown(text);
  }

  function renderAskUserHtml(text) {
    const source = String(text || "").trim();
    if (!source.startsWith("ASK_USER_REQUEST")) return "";
    const jsonPart = source.slice("ASK_USER_REQUEST".length).trim();
    let payload;
    try {
      payload = JSON.parse(jsonPart);
    } catch (_error) {
      return "";
    }
    const questions = Array.isArray(payload?.questions) ? payload.questions : [];
    if (!questions.length) return "";

    const intro = payload.context
      ? `<p class="ask-user-context">${escapeHtml(payload.context)}</p>`
      : "";
    const cards = questions
      .map((question, index) => {
        const prompt = escapeHtml(String(question.prompt || `问题 ${index + 1}`));
        const options = Array.isArray(question.options) ? question.options : [];
        const optionButtons = options.length
          ? `<div class="ask-user-options">${options
              .map(
                (option) =>
                  `<button type="button" class="ask-user-option" data-ask-answer="${escapeAttr(String(option))}">${escapeHtml(String(option))}</button>`,
              )
              .join("")}</div>`
          : `<p class="ask-user-hint muted">请在下方输入框回复</p>`;
        return `<div class="ask-user-card"><div class="ask-user-prompt">${prompt}</div>${optionButtons}</div>`;
      })
      .join("");
    return `<div class="ask-user-panel">${intro}${cards}</div>`;
  }

  function escapeAttr(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll('"', "&quot;")
      .replaceAll("<", "&lt;");
  }

  function renderMarkdown(text) {
    if (window.LuminaMarkdown) {
      return window.LuminaMarkdown.render(text);
    }
    const source = String(text || "");
    return source ? `<p>${escapeHtml(source)}</p>` : "";
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  function applyThreadPayload(payload, { render = true } = {}) {
    if (!Array.isArray(payload?.threads)) return false;
    threads = sortThreadsByUpdatedAt(payload.threads);
    const remoteCurrent = String(payload.current_id || "");
    currentThreadId = threads.some((item) => item.id === remoteCurrent)
      ? remoteCurrent
      : (threads[0]?.id || "");
    saveThreadsLocal();
    if (render) {
      renderThreadList();
      renderCurrentThreadMessages();
      scrollActiveThreadIntoView();
    } else {
      renderThreadList();
      scrollActiveThreadIntoView();
    }
    return true;
  }

  async function syncThreadsFromServer({ render = true } = {}) {
    const remote = await window.SecretaryAPI.request("GET", "/api/chat/threads", null, {
      timeoutMs: 8000,
    });
    return applyThreadPayload(remote, { render });
  }

  async function initThreads() {
    threadListEl.addEventListener("click", (event) => {
      const deleteBtn = event.target.closest("[data-delete-thread-id]");
      if (deleteBtn) {
        event.preventDefault();
        event.stopPropagation();
        void deleteThread(deleteBtn.dataset.deleteThreadId || "");
        return;
      }
      const button = event.target.closest("[data-thread-id]");
      if (!button) return;
      void switchThread(button.dataset.threadId || "");
    });

    try {
      if (await syncThreadsFromServer()) {
        if (threads.length) {
          return;
        }
        await createThread(false);
        return;
      }
    } catch (_error) {
      // Fall back to localStorage below.
    }

    threads = sortThreadsByUpdatedAt(loadThreads());
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
    void pushThreadsToServer();
  }

  async function createThread(clearBackend = true) {
    if (clearBackend && activeRequestController) {
      activeRequestController.abort();
    }
    if (clearBackend) {
      setBusy(false);
      resetTransientUI();
    }
    const thread = {
      id: `t_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
      title: t("thread.new"),
      updatedAt: new Date().toISOString(),
      messages: [],
    };
    threads.unshift(thread);
    currentThreadId = thread.id;
    saveThreadsLocal();
    renderThreadList();
    renderCurrentThreadMessages();
    scrollActiveThreadIntoView();
    try {
      const remote = await window.SecretaryAPI.request(
        "POST",
        "/api/chat/threads",
        { title: t("thread.new") },
        { timeoutMs: 8000 },
      );
      applyThreadPayload(remote, { render: true });
    } catch (_error) {
      // Local thread remains usable when the backend is unavailable.
    }
  }

  async function deleteThread(threadId) {
    if (!threadId) return;
    const index = threads.findIndex((item) => item.id === threadId);
    if (index < 0) return;
    threads.splice(index, 1);
    if (currentThreadId === threadId) {
      if (threads.length) {
        currentThreadId = threads[0].id;
      } else {
        currentThreadId = "";
      }
    }
    saveThreadsLocal();
    renderThreadList();
    renderCurrentThreadMessages();
    scrollActiveThreadIntoView();
    try {
      const remote = await window.SecretaryAPI.request(
        "DELETE",
        `/api/chat/threads/${encodeURIComponent(threadId)}`,
        null,
        { timeoutMs: 8000 },
      );
      applyThreadPayload(remote, { render: true });
    } catch (_error) {
      if (!threads.length) {
        await createThread(false);
      }
    }
  }

  async function switchThread(threadId) {
    if (!threadId || threadId === currentThreadId) return;
    currentThreadId = threadId;
    saveThreadsLocal();
    renderThreadList();
    renderCurrentThreadMessages();
    scrollActiveThreadIntoView();
    try {
      const remote = await window.SecretaryAPI.request(
        "PUT",
        "/api/chat/threads/current",
        { thread_id: threadId },
        { timeoutMs: 8000 },
      );
      applyThreadPayload(remote, { render: false });
    } catch (_error) {
      // Local switch is enough for offline use.
    }
  }

  function scrollActiveThreadIntoView() {
    const active = threadListEl.querySelector(".thread-item-wrap.active");
    active?.scrollIntoView({ block: "nearest" });
  }

  function renderThreadList() {
    threadListEl.innerHTML = threads
      .map((item) => {
        const active = item.id === currentThreadId ? " active" : "";
        const preview = buildThreadPreview(item);
        return (
          `<div class="thread-item-wrap${active}">` +
          `<button class="thread-item${active}" type="button" data-thread-id="${item.id}">` +
          `<div class="thread-item-title">${escapeHtml(item.title || t("thread.new"))}</div>` +
          `<div class="thread-item-preview">${escapeHtml(preview)}</div>` +
          `<div class="thread-item-time">${formatThreadTime(item.updatedAt)}</div>` +
          `</button>` +
          `<button class="thread-item-delete" type="button" data-delete-thread-id="${item.id}" aria-label="${escapeHtml(t("thread.delete"))}">×</button>` +
          `</div>`
        );
      })
      .join("");
  }

  function renderCurrentThreadMessages() {
    resetTransientUI();
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
    if (role === "user" && (thread.title === t("thread.new") || thread.title === "新对话" || !thread.title)) {
      thread.title = buildThreadTitle(text);
    }
    thread.updatedAt = new Date().toISOString();
    threads = sortThreadsByUpdatedAt(threads);
    saveThreadsLocal();
    renderThreadList();
  }

  function getCurrentThread() {
    return threads.find((item) => item.id === currentThreadId) || null;
  }

  function saveThreadsLocal() {
    localStorage.setItem(THREADS_KEY, JSON.stringify(threads));
    localStorage.setItem(CURRENT_THREAD_KEY, currentThreadId);
  }

  async function pushThreadsToServer() {
    await window.SecretaryAPI.request(
      "PUT",
      "/api/chat/threads",
      { current_id: currentThreadId, threads },
      { timeoutMs: 8000 },
    );
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
    if (!compact) return t("thread.new");
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
      return t("thread.empty");
    }
    const last = thread.messages[thread.messages.length - 1];
    const text = String(last?.text || "").replace(/\s+/g, " ").trim();
    if (!text) return t("thread.empty");
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
