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
  const toggleSidebarBtn = document.getElementById("btn-toggle-sidebar");
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

  let busy = false; // 保留用于当前线程快捷检查
  let activeRequestController = null;
  let typingTicker = null;
  let typingStartAt = 0;
  let slowNoticeSent = false;

  // Per-thread concurrent request state:支持多线程同时对话
  // threadId -> { controller, traceId, streamingText, pendingActionId, typingLabel, progressItems }
  const threadState = new Map();
  let threads = [];
  let currentThreadId = "";
  let streamingBubbleEl = null;
  let streamingText = "";
  let streamingRenderPending = false;
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

  // Conversation tree branching state
  let pendingParentId = ""; // when forking, the parent message id for the next send
  let currentTreeData = null; // cached tree view from /tree endpoint
  let showArchived = false; // whether to render archived (soft-deleted) nodes

  // ---- Skill picker (slash command) ----
  const skillPickerEl = document.getElementById("skill-picker");
  let skillCache = null; // cached list of installed skills
  let skillCacheTime = 0;
  let pickerOpen = false;
  let pickerSelectedIndex = -1;
  let pickerItems = []; // current filtered list

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
    if (pickerOpen) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        movePickerSelection(1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        movePickerSelection(-1);
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        confirmPickerSelection();
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeSkillPicker();
        return;
      }
      if (event.key === "Tab") {
        event.preventDefault();
        confirmPickerSelection();
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      chatForm.requestSubmit();
    }
  });

  chatInput.addEventListener("input", () => {
    autoResize();
    handleSlashInput();
    updateSendBtnState();
  });
  pauseBtn.addEventListener("click", pauseCurrentRequest);
  newThreadBtn.addEventListener("click", () => {
    createThread();
  });

  // 侧栏收缩/展开,状态持久化
  if (toggleSidebarBtn) {
    try {
      if (localStorage.getItem("lumina.sidebar.collapsed") === "1") {
        document.body.classList.add("sidebar-collapsed");
      }
    } catch (_e) { /* ignore */ }
    toggleSidebarBtn.addEventListener("click", () => {
      const collapsed = document.body.classList.toggle("sidebar-collapsed");
      try {
        localStorage.setItem("lumina.sidebar.collapsed", collapsed ? "1" : "0");
      } catch (_e) { /* ignore */ }
    });
  }

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

  let autoResizePending = false;
  function autoResize() {
    if (autoResizePending) return;
    autoResizePending = true;
    requestAnimationFrame(() => {
      autoResizePending = false;
      chatInput.style.height = "auto";
      chatInput.style.height = `${Math.min(chatInput.scrollHeight, 160)}px`;
    });
  }

  // 发送按钮呼吸感:有内容时高亮+轻微放大
  function updateSendBtnState() {
    const hasContent = chatInput.value.trim().length > 0;
    sendBtn.classList.toggle("has-content", hasContent && !busy);
  }

  // ---- Skill picker implementation ----

  async function fetchInstalledSkills() {
    // Cache for 60 seconds
    if (skillCache && Date.now() - skillCacheTime < 60000) return skillCache;
    try {
      const data = await window.SecretaryAPI.request("GET", "/api/skills/installed", null, {
        timeoutMs: 5000,
      });
      skillCache = Array.isArray(data) ? data : [];
      skillCacheTime = Date.now();
      return skillCache;
    } catch (_e) {
      return skillCache || [];
    }
  }

  function handleSlashInput() {
    const value = chatInput.value;
    // Trigger only when "/" is the first character
    if (value.startsWith("/")) {
      const query = value.slice(1).toLowerCase();
      openSkillPicker(query);
    } else {
      closeSkillPicker();
    }
  }

  async function openSkillPicker(query) {
    const skills = await fetchInstalledSkills();
    if (!skills.length) {
      closeSkillPicker();
      return;
    }

    pickerItems = query
      ? skills.filter((s) => (s.name || "").toLowerCase().includes(query))
      : skills;

    if (!pickerItems.length) {
      renderSkillPicker([]);
      return;
    }

    pickerSelectedIndex = 0;
    renderSkillPicker(pickerItems);
    pickerOpen = true;
    skillPickerEl.hidden = false;
  }

  function closeSkillPicker() {
    pickerOpen = false;
    pickerSelectedIndex = -1;
    pickerItems = [];
    skillPickerEl.hidden = true;
    skillPickerEl.innerHTML = "";
  }

  function renderSkillPicker(items) {
    skillPickerEl.innerHTML = "";

    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "skill-picker-empty";
      empty.textContent = "没有匹配的技能";
      skillPickerEl.appendChild(empty);
      skillPickerEl.hidden = false;
      pickerOpen = true;
      return;
    }

    const header = document.createElement("div");
    header.className = "skill-picker-header";
    header.textContent = `技能列表 (${items.length})`;
    skillPickerEl.appendChild(header);

    items.forEach((skill, index) => {
      const item = document.createElement("div");
      item.className = `skill-picker-item${index === pickerSelectedIndex ? " is-selected" : ""}`;
      item.dataset.index = String(index);

      const name = document.createElement("span");
      name.className = "skill-picker-item-name";
      name.textContent = skill.name || "(未命名)";

      const desc = document.createElement("span");
      desc.className = "skill-picker-item-desc";
      desc.textContent = skill.description || "";

      item.appendChild(name);
      item.appendChild(desc);

      item.addEventListener("click", () => {
        pickerSelectedIndex = index;
        confirmPickerSelection();
      });
      item.addEventListener("mouseenter", () => {
        pickerSelectedIndex = index;
        updatePickerSelection();
      });

      skillPickerEl.appendChild(item);
    });

    skillPickerEl.hidden = false;
  }

  function updatePickerSelection() {
    const els = skillPickerEl.querySelectorAll(".skill-picker-item");
    els.forEach((el, i) => {
      el.classList.toggle("is-selected", i === pickerSelectedIndex);
    });
    // Scroll selected item into view
    const selected = skillPickerEl.querySelector(".skill-picker-item.is-selected");
    if (selected) {
      selected.scrollIntoView({ block: "nearest" });
    }
  }

  function movePickerSelection(delta) {
    if (!pickerItems.length) return;
    pickerSelectedIndex = (pickerSelectedIndex + delta + pickerItems.length) % pickerItems.length;
    updatePickerSelection();
  }

  function confirmPickerSelection() {
    if (!pickerOpen || pickerSelectedIndex < 0 || !pickerItems[pickerSelectedIndex]) {
      closeSkillPicker();
      return;
    }
    const skill = pickerItems[pickerSelectedIndex];
    const skillName = skill.name || "";
    // Replace "/query" with skill name + space
    chatInput.value = skillName + " ";
    closeSkillPicker();
    autoResize();
    chatInput.focus();
    // Place cursor at end
    const len = chatInput.value.length;
    chatInput.setSelectionRange(len, len);
  }

  // Click outside to close
  document.addEventListener("click", (event) => {
    if (!pickerOpen) return;
    if (!skillPickerEl.contains(event.target) && event.target !== chatInput) {
      closeSkillPicker();
    }
  });

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
      { message: userText, trace_id: "", thread_id: currentThreadId || "", parent_message_id: "" },
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
      { message: userText, trace_id: "", thread_id: currentThreadId || "", parent_message_id: "" },
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

    if (isThreadBusy(currentThreadId)) return;

    welcome.classList.add("hidden");
    appendMessage("user", text);
    chatInput.value = "";
    autoResize();
    setBusy(true);
    slowNoticeSent = false;
    resetProgressLog();
    showTyping(true, t("chat.typing.understand"));
    beginTypingTicker();

    const requestThreadId = currentThreadId;
    try {
      const controller = createActiveController();
      const traceId = createTraceId();
      // 存储 traceId 到线程状态,供 progress 事件路由
      const st = ensureThreadState(requestThreadId);
      st.traceId = traceId;
      void window.SecretaryAPI.subscribeChatProgress(
        traceId,
        (event) => handleProgressEvent(event, traceId),
        controller.signal,
      );
      const isForkSend = Boolean(pendingParentId);
      const chatBody = {
        message: text,
        trace_id: traceId,
        thread_id: currentThreadId || "",
        parent_message_id: pendingParentId || "",
      };
      // Fork intent is consumed once the request is sent.
      if (pendingParentId) {
        pendingParentId = "";
        updateForkBanner();
      }
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

      // 检查用户是否在请求期间切换了线程
      const stillCurrentThread = requestThreadId === currentThreadId;
      const syncRender = isForkSend;

      if (!stillCurrentThread) {
        // 用户已切换到其他线程:后端已持久化回复,只需同步线程列表
        clearStreamingBubble();
        void syncThreadsFromServer({ render: false });
      } else if (response.needs_confirmation) {
        clearStreamingBubble();
        ensureThreadState(currentThreadId).pendingActionId = response.confirmation_action_id;
        appendConfirmation(response);
        void syncThreadsFromServer({ render: syncRender });
      } else if (streamingBubbleEl) {
        finalizeStreamingMessage(response.reply);
        appendGroundingMeta(response);
        void syncThreadsFromServer({ render: syncRender }).then(() => {
          appendGroundingMeta(response);
          void fetchTreeData(currentThreadId);
        });
      } else {
        appendMessage("bot", response.reply);
        appendGroundingMeta(response);
        void syncThreadsFromServer({ render: syncRender }).then(() => {
          appendGroundingMeta(response);
          void fetchTreeData(currentThreadId);
        });
      }
    } catch (error) {
      clearStreamingBubble();
      handleRequestError(error, t("chat.error.reply"));
    } finally {
      // 只清理当前线程的请求状态(如果还在当前线程)
      if (requestThreadId === currentThreadId) {
        finalizeProgressSession();
        endTypingTicker();
        showTyping(false);
        chatInput.focus();
      }
      // 清除 per-thread 状态
      const st = getThreadState(requestThreadId);
      if (st) {
        st.controller = null;
        st.streamingText = "";
        st.traceId = "";
      }
      updateThreadBusyIndicator(requestThreadId);
      // 恢复 busy 状态(如果当前线程没有活跃请求)
      if (!isThreadBusy(currentThreadId)) {
        busy = false;
        sendBtn.disabled = false;
        chatInput.disabled = false;
        pauseBtn.hidden = true;
      }
      activeRequestController = null;
    }
  }

  async function handleConfirm(approved, options = {}) {
    const threadSt = ensureThreadState(currentThreadId);
    if (!threadSt.pendingActionId) return;
    const actionId = threadSt.pendingActionId;
    threadSt.pendingActionId = null;

    const confirmRow = document.querySelector(".confirmation-row");
    if (confirmRow) {
      const status = approved ? `✅ ${t("confirm.allow")}` : `❌ ${t("confirm.deny")}`;
      confirmRow.querySelector(".confirm-actions").innerHTML = `<span class="confirm-status">${escapeHtml(status)}</span>`;
      confirmRow.classList.remove("confirmation-row");
    }

    setBusy(true);
    showTyping(true, t("chat.typing.execute"));
    beginTypingTicker();

    const requestThreadId = currentThreadId;
    try {
      const controller = createActiveController();
      const traceId = createTraceId();
      const st = ensureThreadState(requestThreadId);
      st.traceId = traceId;
      void window.SecretaryAPI.subscribeChatProgress(
        traceId,
        (event) => handleProgressEvent(event, traceId),
        controller.signal,
      );
      const response = await window.SecretaryAPI.request(
        "POST",
        "/api/chat/confirm",
        {
          action_id: actionId,
          approved: approved,
          grant_permanent_read: Boolean(options.grantPermanentRead),
          grant_session_write: Boolean(options.grantSessionWrite),
          trace_id: traceId,
          thread_id: requestThreadId || "",
        },
        {
          signal: controller.signal,
          timeoutMs: 120_000,
        },
      );
      showTyping(false);

      const stillCurrentThread = requestThreadId === currentThreadId;
      if (!stillCurrentThread) {
        clearStreamingBubble();
        void syncThreadsFromServer({ render: false });
      } else if (response.needs_confirmation) {
        clearStreamingBubble();
        ensureThreadState(currentThreadId).pendingActionId = response.confirmation_action_id;
        appendConfirmation(response);
        void syncThreadsFromServer({ render: false });
      } else if (streamingBubbleEl) {
        finalizeStreamingMessage(response.reply);
        appendGroundingMeta(response);
        void syncThreadsFromServer({ render: false }).then(() => {
          appendGroundingMeta(response);
          void fetchTreeData(currentThreadId);
        });
      } else {
        appendMessage("bot", response.reply);
        appendGroundingMeta(response);
        void syncThreadsFromServer({ render: false }).then(() => {
          appendGroundingMeta(response);
          void fetchTreeData(currentThreadId);
        });
      }
    } catch (error) {
      clearStreamingBubble();
      handleRequestError(error, t("chat.error.action"));
    } finally {
      if (requestThreadId === currentThreadId) {
        finalizeProgressSession();
        endTypingTicker();
        showTyping(false);
        chatInput.focus();
      }
      const st = getThreadState(requestThreadId);
      if (st) {
        st.controller = null;
        st.streamingText = "";
        st.traceId = "";
      }
      updateThreadBusyIndicator(requestThreadId);
      if (!isThreadBusy(currentThreadId)) {
        busy = false;
        sendBtn.disabled = false;
        chatInput.disabled = false;
        pauseBtn.hidden = true;
      }
      activeRequestController = null;
    }
  }

  function appendMessage(role, text) {
    appendMessageInternal(role, text, true);
  }

  // 时间标记分隔线:编辑式章节感
  function insertTimeDivider(ts) {
    const d = new Date(ts);
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    const divider = document.createElement("div");
    divider.className = "time-divider";
    divider.innerHTML = `<span class="time-divider-line"></span><span class="time-divider-text">${hh}:${mm}</span><span class="time-divider-line"></span>`;
    messagesEl.appendChild(divider);
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
    appendRawToggle(response);
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

  function appendRawToggle(response) {
    if (!response) return;
    const raw = String(response.raw_reply || "").trim();
    if (!raw) return;
    const finalText = String(response.reply || "").trim();
    if (raw === finalText) return;

    const rows = messagesEl.querySelectorAll(".message.bot");
    const row = rows[rows.length - 1];
    if (!row || row.querySelector(".raw-toggle")) return;

    const bubble = row.querySelector(".bubble");
    if (!bubble) return;

    const wrap = document.createElement("div");
    wrap.className = "raw-toggle";

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "raw-toggle-btn";
    btn.setAttribute("data-tip", "原始输出");
    btn.setAttribute("aria-expanded", "false");
    btn.innerHTML =
      '<svg viewBox="0 0 16 16" width="13" height="13" fill="none" ' +
      'stroke="currentColor" stroke-width="1.5">' +
      '<path d="M8 3C4.5 3 1.5 8 1.5 8s3 5 6.5 5 6.5-5 6.5-5-3-5-6.5-5z"/>' +
      '<circle cx="8" cy="8" r="2"/></svg>';

    const body = document.createElement("div");
    body.className = "raw-toggle-body";
    body.hidden = true;
    body.innerHTML = renderMarkdown(raw);

    btn.addEventListener("click", () => {
      const open = body.hidden;
      body.hidden = !open;
      btn.setAttribute("aria-expanded", String(open));
      btn.classList.toggle("is-open", open);
      if (open) scrollChatToBottom();
    });

    wrap.appendChild(btn);
    wrap.appendChild(body);
    bubble.appendChild(wrap);
  }

  function isRuntimeSummaryMessage(text) {
    const source = String(text || "").trim();
    if (!source) return false;
    return RUNTIME_SUMMARY_RE.test(source);
  }

  function appendMessageInternal(role, text, persist, msgMeta = null) {
    if (isRuntimeSummaryMessage(text)) {
      return;
    }
    let msgId = msgMeta?.id || "";
    let archived = Boolean(msgMeta?.archived);
    if (persist) {
      const created = persistMessage(role, text);
      if (!created) return;
      msgId = created.id;
      archived = created.archived;
    }
    const thread = getCurrentThread();
    const isActiveLeaf = Boolean(msgId) && Boolean(thread) && msgId === (thread.active_leaf_id || "");
    const row = document.createElement("div");
    row.className = `message ${role}${archived ? " archived" : ""}${isActiveLeaf ? " is-active-leaf" : ""}`;
    if (msgId) row.dataset.msgId = msgId;
    const avatarSrc = role === "bot" ? BOT_AVATAR_SRC : "/assets/avatar-user.svg";
    const bubbleClass = "bubble markdown";
    row.innerHTML =
      `<div class="avatar ${role}" aria-label="${avatarLabel(role)}">` +
      `<img src="${avatarSrc}" alt="" aria-hidden="true" /></div>` +
      `<div class="${bubbleClass}">${renderMessageHtml(role, text)}</div>`;
    if (msgId) {
      row.appendChild(buildMsgActionsEl(msgId, role, archived, thread));
    }
    messagesEl.appendChild(row);
    if (persist) {
      row.classList.add("msg-enter");
      row.addEventListener("animationend", () => row.classList.remove("msg-enter"), { once: true });
    }
    scrollChatToBottom();
  }

  function buildMsgActionsEl(msgId, role, archived, thread) {
    const wrap = document.createElement("div");
    wrap.className = "msg-actions";
    // A turn = user question + assistant reply. Forking makes sense only at
    // the end of a turn (the assistant reply); forking from a bare user
    // question would just regenerate the answer, which is rarely useful.
    const canFork = role === "bot";
    if (archived) {
      const restoreBtn = document.createElement("button");
      restoreBtn.type = "button";
      restoreBtn.className = "msg-action-btn";
      restoreBtn.setAttribute("data-tip", "恢复");
      restoreBtn.dataset.action = "restore";
      restoreBtn.dataset.msgId = msgId;
      restoreBtn.innerHTML =
        '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" ' +
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" ' +
        'stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/>' +
        '<path d="M3 4v5h5"/></svg>';
      wrap.appendChild(restoreBtn);
    } else {
      if (canFork) {
        const forkBtn = document.createElement("button");
        forkBtn.type = "button";
        forkBtn.className = "msg-action-btn";
        forkBtn.setAttribute("data-tip", "从此新开分支");
        forkBtn.dataset.action = "fork";
        forkBtn.dataset.msgId = msgId;
        forkBtn.innerHTML =
          '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" ' +
          'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" ' +
          'stroke-linejoin="round"><circle cx="6" cy="6" r="2"/>' +
          '<circle cx="6" cy="18" r="2"/>' +
          '<circle cx="18" cy="12" r="2"/>' +
          '<path d="M6 8v8"/><path d="M8 6h4a4 4 0 0 1 4 4"/>' +
          '<path d="M8 18h4a4 4 0 0 0 4-4"/></svg>';
        wrap.appendChild(forkBtn);
      }
      const rollbackBtn = document.createElement("button");
      rollbackBtn.type = "button";
      rollbackBtn.className = "msg-action-btn";
      rollbackBtn.setAttribute("data-tip", "回退到此");
      rollbackBtn.dataset.action = "rollback";
      rollbackBtn.dataset.msgId = msgId;
      rollbackBtn.innerHTML =
        '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" ' +
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" ' +
        'stroke-linejoin="round"><path d="M9 14L4 9l5-5"/>' +
        '<path d="M4 9h11a5 5 0 0 1 5 5v0a5 5 0 0 1-5 5H8"/></svg>';
      wrap.appendChild(rollbackBtn);
    }
    const switcher = buildSiblingSwitcherEl(thread, msgId);
    if (switcher) wrap.appendChild(switcher);
    return wrap;
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

  let scrollChatPending = false;
  function scrollChatToBottom() {
    if (!mainScrollEl) return;
    if (scrollChatPending) return;
    scrollChatPending = true;
    requestAnimationFrame(() => {
      scrollChatPending = false;
      mainScrollEl.scrollTop = mainScrollEl.scrollHeight;
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
    const normalized = normalizeIdentityText(text);
    if (!normalized) return false;
    if (/你|灵犀|本助手|这个助手/.test(normalized)) return false;
    if (
      /^([A-Za-z0-9][\w./\s-]{1,48}?)\s*(?:项目|仓库|repo)?\s*的?\s*(作者|开发者|创建者|维护者|谁写|谁开发)/i.test(
        normalized,
      )
    ) {
      return true;
    }
    if (
      /(?:找|查|看|请问|帮我).{0,16}?[A-Za-z0-9][\w./\s-]{1,48}?\s*(?:项目|仓库|repo)?\s*的?\s*(作者|开发者|创建者|维护者|谁写|谁开发)/i.test(
        normalized,
      )
    ) {
      return true;
    }
    if (/\bopen\s*[-_]?\s*design\b/i.test(normalized) && /(作者|开发者|创建者|维护者|谁写|谁开发)/.test(normalized)) {
      return true;
    }
    if (/(~|\/Users\/|\/)/.test(normalized) && /(作者|开发者|创建者|维护者|谁写|谁开发)/.test(normalized)) {
      return true;
    }
    return false;
  }

  function isAuthorRequest(text) {
    const normalized = normalizeIdentityText(text);
    if (!normalized) return false;
    if (isThirdPartyProjectAuthorQuestion(normalized)) return false;
    if (
      /谁写的|谁写|谁开发|谁做的|谁制作|谁创造|你的作者|你的开发者|你的创建者|谁是你的作者|谁是你的开发者|你的作者是谁|你的开发者是谁|谁创造了你|谁创造了灵犀|who made you|who created you|who built you|who developed you/i.test(
        normalized,
      )
    ) {
      return true;
    }
    if (/谁.{0,6}写.{0,4}(你|灵犀|lumina)/i.test(normalized)) return true;
    if (/(你|灵犀).{0,8}(作者|开发者|创建者|制作人)/i.test(normalized)) return true;
    if (
      /^(作者|开发者|创建者|制作人)(是谁|哪位|谁)[啊呀吗]?[？?]?$/i.test(normalized) ||
      /谁(开发|做|写|创造)了?(你|灵犀)/i.test(normalized)
    ) {
      return true;
    }
    return false;
  }

  function coreIdentityMatch(text) {
    const normalized = normalizeIdentityText(text);
    if (!normalized) return false;
    if (isAuthorRequest(normalized)) return false;
    if (/帮我写|帮我做|帮我撰|帮我起草|帮我编辑|帮我润色|写一份|写个|撰写|起草/.test(normalized)) {
      return false;
    }
    if (/我的/.test(normalized) && /自我介绍/.test(normalized) && !/你/.test(normalized)) return false;
    if (/自我介绍/.test(normalized)) return true;
    if (/^(介绍一下|介绍下|介绍)$/.test(normalized)) return true;
    if (normalized === "你是谁" || normalized === "你是什么" || /^你是谁[啊呀吗]?[？?]?$/.test(normalized)) return true;
    if (
      /你是什么|介绍一下你|介绍一下灵犀|说说你自己|你叫什么|你叫啥|你是做什么|你是干啥|你能做什么|你会什么|你都能干什么|你会干什么|说说你的能力|你有什么功能|什么是灵犀|灵犀是什么|who are you|what are you|what is lumina/i.test(
        normalized,
      )
    ) {
      return true;
    }
    if (/(做|来|请|给).{0,4}自我介绍/.test(normalized)) return true;
    if (/介绍(一下)?(你|你自己|灵犀|lumina)/i.test(normalized)) return true;
    if (/(你|灵犀).{0,6}介绍/i.test(normalized)) return true;
    if (/再.{0,8}介绍.{0,8}(你|自己|灵犀)?/.test(normalized)) return true;
    return false;
  }

  function isIdentityRepeatRequest(text, messages) {
    const normalized = normalizeIdentityText(text);
    if (!/再说一遍|再说一次|再来一遍|再来一次|再讲一遍|重复一遍|再介绍/.test(normalized)) {
      return false;
    }
    if (/(你|自己|灵犀|介绍|是谁|做什么|能力|功能)/.test(normalized)) return true;
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
    const st = getThreadState(currentThreadId);
    if (st) st.pendingActionId = null;
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

  function handleProgressEvent(event, traceId) {
    const kind = String(event?.kind || "");

    // 通过 traceId 找到对应的线程
    let eventThreadId = "";
    for (const [tid, st] of threadState) {
      if (st.traceId === traceId) {
        eventThreadId = tid;
        break;
      }
    }
    const isCurrentThread = eventThreadId === currentThreadId;

    // 流式回复:只在当前线程的视图里更新 bubble
    if (isCurrentThread) {
      if (kind === "reply_start") {
        beginStreamingBubble();
      } else if (kind === "reply_delta" && event?.delta) {
        appendStreamingDelta(String(event.delta));
      } else if (kind === "reply_end") {
        // 回复内容已全部通过流式发送,停止慢提示 ticker 避免「结果已显示却提示处理慢」
        endTypingTicker();
        showTyping(false);
      }
    } else if (eventThreadId) {
      // 非当前线程:缓冲流式文本
      if (kind === "reply_delta" && event?.delta) {
        const st = getThreadState(eventThreadId);
        if (st) {
          st.streamingText += String(event.delta);
          st.typingLabel = t("chat.typing.understand");
        }
      }
    }

    const label = String(event?.label || "").trim();
    if (!label && !kind.startsWith("reply_")) return;

    // 进度面板:只在当前线程显示
    if (isCurrentThread && progressEl && progressListEl && label && !kind.startsWith("reply_")) {
      appendProgressItem(event, label);
      scrollChatToBottom();
    }

    // 缓存非当前线程的 typing label
    if (!isCurrentThread && eventThreadId) {
      const st = getThreadState(eventThreadId);
      if (st && label) st.typingLabel = label;
    }

    if (isCurrentThread) {
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
    if (streamingRenderPending) return;
    streamingRenderPending = true;
    const renderThreadId = currentThreadId;
    requestAnimationFrame(() => {
      streamingRenderPending = false;
      // Re-verify thread hasn't switched before updating DOM (problem 6)
      if (renderThreadId !== currentThreadId) return;
      if (!streamingBubbleEl) return;
      streamingBubbleEl.innerHTML = renderMarkdown(streamingText);
      scrollChatToBottom();
    });
  }

  function finalizeStreamingMessage(finalText) {
    if (!streamingBubbleEl) {
      appendMessage("bot", finalText);
      return;
    }
    const row = streamingBubbleEl.closest(".message");
    streamingBubbleEl.innerHTML = renderMessageHtml("bot", finalText);
    const msg = persistMessage("bot", finalText);
    streamingBubbleEl = null;
    streamingText = "";
    scrollChatToBottom();
    if (row && msg) {
      row.classList.remove("streaming");
      row.dataset.msgId = msg.id;
      const thread = getCurrentThread();
      if (thread && msg.id === (thread.active_leaf_id || "")) {
        row.classList.add("is-active-leaf");
      }
      row.appendChild(buildMsgActionsEl(msg.id, "bot", false, thread));
    }
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

  // ===== Per-thread state management =====

  function getThreadState(tid) {
    return threadState.get(tid) || null;
  }

  function ensureThreadState(tid) {
    if (!threadState.has(tid)) {
      threadState.set(tid, {
        controller: null,
        traceId: "",
        streamingText: "",
        pendingActionId: null,
        typingLabel: "",
        progressItems: [],
      });
    }
    return threadState.get(tid);
  }

  function isThreadBusy(tid) {
    const st = getThreadState(tid);
    return Boolean(st && st.controller);
  }

  function saveCurrentStreamingState() {
    if (!currentThreadId) return;
    const st = ensureThreadState(currentThreadId);
    st.streamingText = streamingText;
    st.typingLabel = typingTextEl?.textContent || "";
  }

  function restoreThreadStreamingState(tid) {
    const st = getThreadState(tid);
    if (!st || !st.controller) {
      // 没有活跃请求,清理流式状态
      streamingBubbleEl = null;
      streamingText = "";
      return;
    }
    // 有活跃请求,恢复流式 bubble
    streamingText = st.streamingText || "";
    if (streamingText) {
      beginStreamingBubble();
      streamingBubbleEl.innerHTML = renderMarkdown(streamingText);
      scrollChatToBottom();
    }
    // 恢复 typing 指示器
    if (st.typingLabel) {
      showTyping(true, st.typingLabel);
    }
  }

  function setThreadBusy(tid, value) {
    const st = ensureThreadState(tid);
    if (value) {
      // busy 由 controller 的存在决定
    }
    if (!value) {
      st.controller = null;
      st.streamingText = "";
      st.typingLabel = "";
      st.progressItems = [];
    }
    // 更新线程列表指示器
    updateThreadBusyIndicator(tid);
  }

  function updateThreadBusyIndicator(tid) {
    const wrap = threadListEl.querySelector(
      `.thread-item-wrap[data-thread-id="${tid}"]`,
    );
    if (!wrap) return;
    const busy = isThreadBusy(tid);
    wrap.classList.toggle("is-busy", busy);
  }

  function updateAllThreadBusyIndicators() {
    for (const tid of threadState.keys()) {
      updateThreadBusyIndicator(tid);
    }
  }

  function setBusy(value) {
    busy = value;
    // 只禁用当前线程的输入,不影响其他线程
    sendBtn.disabled = value;
    chatInput.disabled = value;
    pauseBtn.hidden = !value;
    if (value) {
      setThreadBusy(currentThreadId, true);
    }
  }

  function createActiveController() {
    const controller = new AbortController();
    activeRequestController = controller;
    const st = ensureThreadState(currentThreadId);
    st.controller = controller;
    updateThreadBusyIndicator(currentThreadId);
    return controller;
  }

  function clearActiveController() {
    activeRequestController = null;
    setThreadBusy(currentThreadId, false);
  }

  function pauseCurrentRequest() {
    if (!activeRequestController) return;
    activeRequestController.abort();
    activeRequestController = null;
    setThreadBusy(currentThreadId, false);
    busy = false;
    sendBtn.disabled = false;
    chatInput.disabled = false;
    pauseBtn.hidden = true;
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
    const idx = source.indexOf("ASK_USER_REQUEST");
    if (idx === -1) return "";
    let jsonPart = source.slice(idx + "ASK_USER_REQUEST".length).trim();
    jsonPart = jsonPart.replace(/^\s*```(?:json)?\s*/i, "").replace(/\s*```\s*$/, "").trim();
    if (!jsonPart.startsWith("{")) {
      const match = jsonPart.match(/\{[\s\S]*\}/);
      if (match) jsonPart = match[0].trim();
    }
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
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
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
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function reconcileMessageIds() {
    // After syncThreadsFromServer({ render: false }), the internal threads
    // state carries server-assigned message ids, but the DOM still holds
    // locally-generated ids from optimistic rendering. Update data-msg-id
    // on each row (and its action buttons) so fork/rollback/restore send
    // the correct server id to the backend.
    const thread = getCurrentThread();
    if (!thread || !Array.isArray(thread.messages)) return;
    const path = computeActivePath(thread);
    const rows = Array.from(messagesEl.querySelectorAll(".message"));
    // Safety: only reconcile when DOM row count matches the active path.
    // A mismatch means the DOM is stale (thread switch, archived toggle,
    // etc.) and a full re-render is needed instead.
    if (rows.length !== path.length) return;
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      const newId = path[i].id;
      if (!newId || row.dataset.msgId === newId) continue;
      row.dataset.msgId = newId;
      row.querySelectorAll("[data-msg-id]").forEach((btn) => {
        btn.dataset.msgId = newId;
      });
    }
  }

  function applyThreadPayload(payload, { render = true } = {}) {
    if (!Array.isArray(payload?.threads)) return false;
    threads = sortThreadsByUpdatedAt(
      payload.threads.map((item) => {
        const t = migrateThreadMessages({ ...item });
        delete t._migrated;
        return t;
      }),
    );
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
      reconcileMessageIds();
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
    // 不再中断之前的请求:保存当前线程状态后切换
    if (clearBackend) {
      saveCurrentStreamingState();
      streamingBubbleEl = null;
      streamingText = "";
      busy = false;
      sendBtn.disabled = false;
      chatInput.disabled = false;
      pauseBtn.hidden = true;
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
    updateAllThreadBusyIndicators();
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
    // 保存当前线程的流式状态(不中断请求)
    saveCurrentStreamingState();
    // 清理当前视图的 streaming bubble(会在 renderCurrentThreadMessages 中重建)
    streamingBubbleEl = null;
    streamingText = "";
    // 切换线程
    currentThreadId = threadId;
    saveThreadsLocal();
    renderThreadList();
    renderCurrentThreadMessages();
    scrollActiveThreadIntoView();
    // 恢复新线程的流式状态(如果有活跃请求)
    restoreThreadStreamingState(threadId);
    // 更新输入框状态:新线程可能没有活跃请求
    const threadBusy = isThreadBusy(threadId);
    busy = threadBusy;
    sendBtn.disabled = threadBusy;
    chatInput.disabled = threadBusy;
    pauseBtn.hidden = !threadBusy;
    if (!threadBusy) {
      chatInput.focus();
    }
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
        const busyCls = isThreadBusy(item.id) ? " is-busy" : "";
        const preview = buildThreadPreview(item);
        const title = escapeHtml(item.title || t("thread.new"));
        return (
          `<div class="thread-item-wrap${active}${busyCls}" data-thread-id="${item.id}" data-tooltip="${title}">` +
          `<button class="thread-item${active}" type="button" data-thread-id="${item.id}">` +
          `<div class="thread-item-title">${title}</div>` +
          `<div class="thread-item-preview">${escapeHtml(preview)}</div>` +
          `<div class="thread-item-time">${formatThreadTime(item.updatedAt)}</div>` +
          `</button>` +
          `<button class="thread-item-delete" type="button" data-delete-thread-id="${item.id}" aria-label="${escapeHtml(t("thread.delete"))}">×</button>` +
          `</div>`
        );
      })
      .join("");
  }

  // 动态 hero 问候语:根据时段/节气/月相
  function updateHeroGreeting() {
    if (!window.LuminaLunar) return;
    const titleEl = document.getElementById("hero-title");
    const subEl = document.getElementById("hero-sub");
    if (!titleEl) return;
    const g = window.LuminaLunar.getGreeting(new Date());
    titleEl.innerHTML = g.main;
    if (subEl && g.sub) subEl.textContent = g.sub;
  }

  function renderCurrentThreadMessages() {
    resetTransientUI();
    messagesEl.innerHTML = "";
    ensureChatToolbar();
    ensureSidebarArchiveBtn();
    const thread = getCurrentThread();
    if (!thread || !Array.isArray(thread.messages) || thread.messages.length === 0) {
      welcome.classList.remove("hidden");
      updateHeroGreeting();
      return;
    }
    welcome.classList.add("hidden");
    const path = computeActivePath(thread);
    let lastMsgTime = null;
    for (const item of path) {
      // 时间标记:与上一条间隔超过 30 分钟则插入分隔线
      const itemTime = item.timestamp ? new Date(item.timestamp).getTime() : null;
      if (itemTime !== null) {
        if (lastMsgTime !== null && (itemTime - lastMsgTime) > 30 * 60 * 1000) {
          insertTimeDivider(itemTime);
        }
        // Update lastMsgTime even if it was null, so subsequent messages
        // have a baseline to compare against.
        lastMsgTime = itemTime;
      }
      appendMessageInternal(item.role, item.text, false, { id: item.id, archived: item.archived });
    }
    scrollChatToBottom();
    void fetchTreeData(currentThreadId);
  }

  // Walk parent_id chain from active_leaf_id back to root, then reverse.
  // Filters archived nodes unless showArchived is on (archived appended at end).
  function computeActivePath(thread) {
    if (!thread || !Array.isArray(thread.messages)) return [];
    const byId = new Map();
    for (const m of thread.messages) {
      if (m && m.id) byId.set(m.id, m);
    }
    if (!thread.active_leaf_id) {
      // Legacy fallback: render all messages in storage order.
      return thread.messages.filter((m) => !m.archived || showArchived);
    }
    const activePath = [];
    const seen = new Set();
    let cur = thread.active_leaf_id;
    let guard = 0;
    while (cur && byId.has(cur) && !seen.has(cur) && guard < 1000) {
      seen.add(cur);
      activePath.push(byId.get(cur));
      cur = byId.get(cur).parent_id || "";
      guard++;
    }
    activePath.reverse();
    if (!showArchived) {
      return activePath.filter((m) => !m.archived);
    }
    // showArchived: active path (non-archived) + archived nodes appended.
    const activeIds = new Set(activePath.map((m) => m.id));
    const archivedExtra = thread.messages.filter(
      (m) => m.archived && !activeIds.has(m.id),
    );
    return [...activePath.filter((m) => !m.archived), ...archivedExtra];
  }

  function computeSiblings(thread, msgId) {
    if (!thread || !Array.isArray(thread.messages) || !msgId) return [];
    const msg = thread.messages.find((m) => m.id === msgId);
    if (!msg) return [];
    const parentId = msg.parent_id || "";
    return thread.messages.filter((m) => (m.parent_id || "") === parentId);
  }

  // Find the deepest leaf in a subtree rooted at rootId by following first
  // non-archived child chain (falls back to first child if all archived).
  function findDeepestLeaf(thread, rootId) {
    if (!thread || !Array.isArray(thread.messages) || !rootId) return rootId;
    const childrenMap = new Map();
    for (const m of thread.messages) {
      const pid = m.parent_id || "";
      if (!childrenMap.has(pid)) childrenMap.set(pid, []);
      childrenMap.get(pid).push(m);
    }
    let leaf = rootId;
    const guardSeen = new Set();
    let guard = 0;
    while (childrenMap.has(leaf) && !guardSeen.has(leaf) && guard < 1000) {
      guardSeen.add(leaf);
      const children = childrenMap.get(leaf);
      const next = children.find((m) => !m.archived) || children[0];
      if (!next) break;
      leaf = next.id;
      guard++;
    }
    return leaf;
  }

  function buildSiblingSwitcherEl(thread, msgId) {
    if (!thread || !msgId) return null;
    const siblings = computeSiblings(thread, msgId);
    if (siblings.length <= 1) return null;
    const idx = siblings.findIndex((s) => s.id === msgId);
    if (idx < 0) return null;
    const wrap = document.createElement("div");
    wrap.className = "sibling-switcher";
    const prev = document.createElement("button");
    prev.type = "button";
    prev.className = "sibling-nav";
    prev.setAttribute("data-tip", "上一分支");
    prev.textContent = "‹";
    prev.dataset.action = "sibling-prev";
    prev.dataset.msgId = msgId;
    prev.disabled = idx === 0;
    const count = document.createElement("span");
    count.className = "sibling-count";
    count.textContent = `${idx + 1}/${siblings.length}`;
    const next = document.createElement("button");
    next.type = "button";
    next.className = "sibling-nav";
    next.setAttribute("data-tip", "下一分支");
    next.textContent = "›";
    next.dataset.action = "sibling-next";
    next.dataset.msgId = msgId;
    next.disabled = idx === siblings.length - 1;
    wrap.appendChild(prev);
    wrap.appendChild(count);
    wrap.appendChild(next);
    return wrap;
  }

  function generateMessageId() {
    let hex = "";
    if (window.crypto?.getRandomValues) {
      const arr = new Uint8Array(4);
      window.crypto.getRandomValues(arr);
      hex = Array.from(arr, (b) => b.toString(16).padStart(2, "0")).join("");
    } else {
      hex = Math.random().toString(16).slice(2, 10).padStart(8, "0");
    }
    return `m_${hex}`;
  }

  function persistMessage(role, text) {
    if (isRuntimeSummaryMessage(text)) {
      return null;
    }
    const thread = getCurrentThread();
    if (!thread) return null;
    const msg = {
      id: generateMessageId(),
      parent_id: thread.active_leaf_id || "",
      role,
      text: String(text || ""),
      timestamp: new Date().toISOString(),
      archived: false,
    };
    thread.messages.push(msg);
    thread.active_leaf_id = msg.id;
    // NOTE: Do not truncate messages here. Blindly slicing the array breaks
    // parent_id chains — surviving messages may reference deleted parents,
    // causing computeActivePath to silently drop messages. Message retention
    // should be managed by the server (archival/soft-delete) instead.
    if (role === "user") {
      thread.title = buildThreadTitle(text);
    }
    thread.updatedAt = new Date().toISOString();
    threads = sortThreadsByUpdatedAt(threads);
    saveThreadsLocal();
    renderThreadList();
    return msg;
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
          const migrated = migrateThreadMessages({ ...item, messages });
          if (migrated._migrated) {
            changed = true;
            delete migrated._migrated;
          }
          return migrated;
        });
      if (changed) {
        localStorage.setItem(THREADS_KEY, JSON.stringify(valid));
      }
      return sortThreadsByUpdatedAt(valid);
    } catch (_error) {
      return [];
    }
  }

  // Migrate legacy flat messages (no id/parent_id/active_leaf_id/archived)
  // into tree nodes with chained parent_id and active_leaf_id at the last message.
  function migrateThreadMessages(thread) {
    if (!thread || !Array.isArray(thread.messages)) return thread;
    let prevId = "";
    for (const msg of thread.messages) {
      if (!msg || typeof msg !== "object") continue;
      if (!msg.id) {
        msg.id = generateMessageId();
        thread._migrated = true;
      }
      if (msg.parent_id === undefined || msg.parent_id === null) {
        msg.parent_id = prevId;
        thread._migrated = true;
      }
      if (msg.archived === undefined || msg.archived === null) {
        msg.archived = false;
        thread._migrated = true;
      }
      prevId = msg.id;
    }
    if (!thread.active_leaf_id) {
      thread.active_leaf_id = thread.messages.length
        ? thread.messages[thread.messages.length - 1].id
        : "";
      thread._migrated = true;
    }
    return thread;
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
    const path = computeActivePath(thread).filter((m) => !m.archived);
    const last = path.length ? path[path.length - 1] : thread.messages[thread.messages.length - 1];
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

  // ---- Conversation tree: fork / rollback / restore / sibling navigation ----

  async function fetchTreeData(threadId) {
    if (!threadId) {
      currentTreeData = null;
      return;
    }
    try {
      currentTreeData = await window.SecretaryAPI.request(
        "GET",
        `/api/chat/threads/${encodeURIComponent(threadId)}/tree`,
        null,
        { timeoutMs: 5000 },
      );
      // Tag with thread id so the map module can reject stale updates
      // after a thread switch.
      if (currentTreeData) currentTreeData._threadId = threadId;
      // Live-update the map if it's currently open.
      if (window.ConversationMapModule && window.ConversationMapModule.isOpen()) {
        window.ConversationMapModule.update(currentTreeData);
      }
    } catch (_error) {
      currentTreeData = null;
    }
  }

  function setForkParent(msgId) {
    pendingParentId = msgId || "";
    updateForkBanner();
    if (pendingParentId) {
      chatInput.focus();
    }
  }

  function cancelFork() {
    pendingParentId = "";
    updateForkBanner();
    chatInput.focus();
  }

  function updateForkBanner() {
    let banner = document.getElementById("fork-banner");
    if (pendingParentId) {
      if (!banner) {
        banner = document.createElement("div");
        banner.id = "fork-banner";
        banner.className = "fork-banner";
        const composerWrap = document.querySelector(".composer-wrap");
        if (composerWrap && composerWrap.parentElement) {
          composerWrap.parentElement.insertBefore(banner, composerWrap);
        }
      }
      banner.innerHTML = "";
      const label = document.createElement("span");
      label.className = "fork-banner-label";
      label.textContent = "将从这条消息分叉新对话";
      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "fork-banner-cancel";
      cancelBtn.textContent = "取消";
      cancelBtn.addEventListener("click", cancelFork);
      banner.appendChild(label);
      banner.appendChild(cancelBtn);
      chatInput.classList.add("fork-pending");
    } else {
      if (banner) banner.remove();
      chatInput.classList.remove("fork-pending");
    }
  }

  async function rollbackToMessage(msgId) {
    if (!msgId || !currentThreadId || busy) return;
    if (!window.confirm("确定回退到此节点？之后的消息将被归档。")) return;
    setBusy(true);
    try {
      const remote = await window.SecretaryAPI.request(
        "POST",
        `/api/chat/threads/${encodeURIComponent(currentThreadId)}/rollback`,
        { to_message_id: msgId },
        { timeoutMs: 8000 },
      );
      applyThreadPayload(remote, { render: true });
      void fetchTreeData(currentThreadId);
    } catch (error) {
      appendMessage("bot", `回退失败: ${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function restoreMessage(msgId) {
    if (!msgId || !currentThreadId || busy) return;
    setBusy(true);
    try {
      const remote = await window.SecretaryAPI.request(
        "POST",
        `/api/chat/threads/${encodeURIComponent(currentThreadId)}/restore`,
        { message_id: msgId },
        { timeoutMs: 8000 },
      );
      applyThreadPayload(remote, { render: true });
      void fetchTreeData(currentThreadId);
    } catch (error) {
      appendMessage("bot", `恢复失败: ${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function switchSibling(msgId, direction) {
    if (!msgId || !currentThreadId || busy) return;
    const thread = getCurrentThread();
    if (!thread) return;
    const siblings = computeSiblings(thread, msgId);
    if (siblings.length <= 1) return;
    const idx = siblings.findIndex((s) => s.id === msgId);
    if (idx < 0) return;
    const nextIdx = direction === "next" ? idx + 1 : idx - 1;
    if (nextIdx < 0 || nextIdx >= siblings.length) return;
    const leafId = findDeepestLeaf(thread, siblings[nextIdx].id);
    setBusy(true);
    try {
      const remote = await window.SecretaryAPI.request(
        "PUT",
        `/api/chat/threads/${encodeURIComponent(currentThreadId)}/active-leaf`,
        { leaf_id: leafId },
        { timeoutMs: 8000 },
      );
      applyThreadPayload(remote, { render: true });
      void fetchTreeData(currentThreadId);
    } catch (error) {
      appendMessage("bot", `切换分支失败: ${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  function ensureChatToolbar() {
    let toolbar = document.getElementById("chat-toolbar");
    if (!toolbar) {
      toolbar = document.createElement("div");
      toolbar.id = "chat-toolbar";
      toolbar.className = "chat-toolbar";
      const mapBtn = document.createElement("button");
      mapBtn.type = "button";
      mapBtn.id = "btn-map-toggle";
      mapBtn.className = "map-toggle-btn js-map-toggle";
      mapBtn.setAttribute("data-tip", "对话地图");
      toolbar.appendChild(mapBtn);
      if (messagesEl.parentElement) {
        messagesEl.parentElement.insertBefore(toolbar, messagesEl);
      }
    }
  }

  function ensureSidebarArchiveBtn() {
    const sidebar = document.querySelector(".chat-sidebar");
    if (!sidebar) return;
    let footer = sidebar.querySelector(".sidebar-footer");
    if (!footer) {
      footer = document.createElement("div");
      footer.className = "sidebar-footer";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sidebar-archive-btn tip-right";
      btn.setAttribute("data-tip", "显示已归档");
      btn.setAttribute("aria-pressed", String(showArchived));
      btn.innerHTML =
        '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" ' +
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" ' +
        'stroke-linejoin="round" aria-hidden="true">' +
        '<rect x="3" y="4" width="18" height="4" rx="1"/>' +
        '<path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8"/>' +
        '<path d="M10 12h4"/></svg>';
      btn.addEventListener("click", () => {
        showArchived = !showArchived;
        btn.setAttribute("aria-pressed", String(showArchived));
        btn.classList.toggle("is-active", showArchived);
        renderCurrentThreadMessages();
      });
      footer.appendChild(btn);
      sidebar.appendChild(footer);
    }
    const btn = footer.querySelector(".sidebar-archive-btn");
    if (btn) {
      btn.setAttribute("aria-pressed", String(showArchived));
      btn.classList.toggle("is-active", showArchived);
    }
  }

  // Event delegation for message action buttons.
  messagesEl.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    const msgId = btn.dataset.msgId;
    if (!action) return;
    if (action === "fork") {
      setForkParent(msgId);
    } else if (action === "rollback") {
      void rollbackToMessage(msgId);
    } else if (action === "restore") {
      void restoreMessage(msgId);
    } else if (action === "sibling-prev") {
      void switchSibling(msgId, "prev");
    } else if (action === "sibling-next") {
      void switchSibling(msgId, "next");
    } else if (action === "cancel-fork") {
      cancelFork();
    }
  });

  // Esc cancels fork mode.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && pendingParentId) {
      cancelFork();
    }
  });

  // Expose minimal entry points for cross-module communication (e.g. conversation map).
  window.ChatModule = {
    getCurrentThreadId: () => currentThreadId,
    refresh: () => syncThreadsFromServer({ render: true }),
    // Map a message id to its turn id in the tree, for chat↔map linkage.
    findTurnIdForMessage: (msgId) => findTurnIdForMessage(msgId),
  };

  // Refresh current thread when conversation map switches active leaf.
  document.addEventListener("conversation:active-leaf-changed", () => {
    void syncThreadsFromServer({ render: true });
  });

  // Chat ↔ Map linkage: hovering a message row highlights the corresponding
  // node in the conversation map (if open).
  messagesEl.addEventListener("mouseover", (event) => {
    const row = event.target.closest(".message[data-msg-id]");
    if (!row) return;
    const msgId = row.dataset.msgId;
    if (!msgId) return;
    if (!window.ConversationMapModule || !window.ConversationMapModule.isOpen()) return;
    const turnId = findTurnIdForMessage(msgId);
    if (turnId) window.ConversationMapModule.highlightNode(turnId);
  });

  messagesEl.addEventListener("mouseout", (event) => {
    const row = event.target.closest(".message[data-msg-id]");
    if (!row) return;
    // Only clear when the cursor leaves the message row entirely (not when
    // moving between child elements within the same row).
    const next = event.relatedTarget;
    if (next && next.closest && next.closest(".message[data-msg-id]") === row) return;
    if (window.ConversationMapModule && window.ConversationMapModule.isOpen()) {
      window.ConversationMapModule.highlightNode("");
    }
  });

  // Look up the turn id that contains a given message id (user or assistant).
  function findTurnIdForMessage(msgId) {
    if (!currentTreeData || !Array.isArray(currentTreeData.nodes)) return "";
    for (const node of currentTreeData.nodes) {
      if (node.id === msgId) return node.id;
      if (node.user_message_id === msgId) return node.id;
      if (node.assistant_message_id === msgId) return node.id;
    }
    return "";
  }
})();
