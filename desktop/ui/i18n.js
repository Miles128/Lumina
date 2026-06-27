(function () {
  "use strict";

  const UI_PREFS_KEY = "lumina.ui.preferences.v1";

  const STRINGS = {
    "app.name": { en: "Lumina", zh: "灵犀" },
    "app.title": { en: "Lumina", zh: "灵犀" },
    "user.me": { en: "Me", zh: "我" },
    "bot.name": { en: "Lumina", zh: "灵犀" },

    "menu.skills": { en: "Skills", zh: "技能" },
    "menu.settings": { en: "Settings", zh: "设置" },
    "menu.knowledge": { en: "Knowledge", zh: "知识库" },
    "menu.sync": { en: "Sync", zh: "同步" },
    "menu.about": { en: "About", zh: "关于" },

    "about.title": { en: "About Lumina", zh: "关于灵犀" },
    "about.developer": { en: "Developer", zh: "开发者" },
    "about.email": { en: "Email", zh: "邮箱" },
    "about.version": { en: "Version", zh: "版本号" },
    "action.close": { en: "Close", zh: "关闭" },
    "action.send": { en: "Send", zh: "发送" },
    "action.pause": { en: "Pause", zh: "暂停" },
    "action.save": { en: "Save", zh: "保存" },

    "chat.newThread": { en: "New chat", zh: "新对话" },
    "chat.welcome": { en: "How can I help?", zh: "有什么可以帮你？" },
    "chat.placeholder": { en: "Message", zh: "输入消息" },
    "chat.processing": { en: "Working…", zh: "正在处理…" },
    "chat.typing.understand": { en: "Understanding your question…", zh: "正在理解你的问题…" },
    "chat.typing.instant": { en: "Replying…", zh: "正在回复…" },
    "chat.typing.gather": { en: "Gathering relevant info…", zh: "正在整理相关信息…" },
    "chat.typing.tools": { en: "Running tools…", zh: "正在调用工具处理…" },
    "chat.typing.almost": { en: "Almost done…", zh: "还在继续处理，马上给你结果…" },
    "chat.typing.slow": { en: "This is taking a while — tap Pause to stop.", zh: "这次耗时较长，你可以点「暂停」先中止。" },
    "chat.typing.organize": { en: "Preparing reply…", zh: "正在整理回复…" },
    "chat.typing.sync": { en: "Syncing data…", zh: "正在同步数据…" },
    "chat.typing.execute": { en: "Executing…", zh: "正在执行操作…" },
    "chat.typing.subagent": { en: "Spawning sub-agent…", zh: "正在派生子 Agent…" },
    "chat.confirm.subagent": { en: "Sub-agent action", zh: "子 Agent 操作" },
    "chat.subagent.tree": { en: "Sub-agents", zh: "子 Agent 会话树" },
    "chat.subagent.running": { en: "Running", zh: "运行中" },
    "chat.subagent.paused": { en: "Awaiting confirmation", zh: "等待确认" },
    "chat.subagent.done": { en: "Done", zh: "已完成" },
    "chat.subagent.failed": { en: "Failed", zh: "失败" },
    "chat.slowNotice": {
      en: "This is slower than usual — still working. Tap Pause to stop.",
      zh: "这次处理有点慢，我还在继续。你可以点「暂停」先停下。",
    },
    "chat.paused": { en: "Request paused. Send another message anytime.", zh: "已暂停这次请求。你可以继续发下一条。" },
    "chat.timeout": {
      en: "Timed out before a result arrived. Try narrowing the scope.",
      zh: "这次等待超时，我还没拿到结果。你可以让我缩小范围后再试一次。",
    },
    "chat.error.reply": { en: "Reply failed", zh: "回答失败" },
    "chat.error.sync": { en: "Sync failed", zh: "同步失败" },
    "chat.error.action": { en: "Action failed", zh: "操作失败" },
    "chat.grounding.verified": { en: "Verified via file tools", zh: "已通过文件工具核实" },
    "chat.grounding.unverified": { en: "Unverified", zh: "未核实" },
    "chat.grounding.unverifiedNoTools": {
      en: "Paths cited but no file tools were used",
      zh: "回复含路径但未调用读文件工具",
    },
    "chat.grounding.unverifiedSimulated": {
      en: "Directory listing may be simulated (no list_dir/file_read)",
      zh: "疑似伪造目录列表，未调用 list_dir",
    },
    "chat.grounding.unverifiedMismatch": {
      en: "Some paths not found in tool output",
      zh: "部分路径未出现在工具结果中",
    },
    "chat.sync.user": { en: "Sync all data", zh: "同步全部数据" },
    "chat.sync.done": { en: "Sync complete — {n} memories written.", zh: "同步完成，写入 {n} 条记忆。" },

    "prompt.reading": { en: "Summarize what I've been reading lately", zh: "总结一下我最近在读什么" },
    "prompt.schedule": { en: "What's on my schedule and todos today?", zh: "帮我看看今天的日程和待办" },
    "prompt.profile": { en: "What does my personal profile look like?", zh: "我的个人信息画像是什么样的" },
    "prompt.reading.label": { en: "Recent reading", zh: "最近在读什么" },
    "prompt.schedule.label": { en: "Today's plan", zh: "今天安排" },
    "prompt.profile.label": { en: "My profile", zh: "个人画像" },

    "token.label": { en: "Token", zh: "Token" },
    "model.loading": { en: "Loading…", zh: "加载中…" },
    "model.unset": { en: "No model", zh: "未指定模型" },
    "model.unconfigured": { en: "Not configured", zh: "未配置模型" },
    "model.current": { en: "Current model", zh: "当前大模型" },
    "token.usage": { en: "Total token usage", zh: "累计 token 消耗" },

    "settings.title": { en: "Settings", zh: "设置" },
    "settings.loading": { en: "Loading…", zh: "加载中…" },
    "settings.loadFailed": { en: "Failed to load", zh: "加载失败" },
    "settings.agent": { en: "Agent", zh: "Agent" },
    "settings.sources": { en: "Sources", zh: "数据源" },
    "settings.profile": { en: "Profile", zh: "个人画像" },
    "settings.llm": { en: "LLM", zh: "大模型" },
    "settings.soul": { en: "SOUL", zh: "人格 SOUL" },
    "settings.memory": { en: "Memory", zh: "持久记忆" },
    "settings.mcp": { en: "MCP Tools", zh: "MCP 工具" },
    "settings.shibei": { en: "Shibei KB", zh: "Shibei 知识库" },
    "settings.appearance": { en: "Appearance", zh: "界面" },

    "appearance.title": { en: "Appearance", zh: "界面" },
    "appearance.desc": {
      en: "Density, reading width, and display language.",
      zh: "调整密度、阅读宽度与界面语言。",
    },
    "appearance.language": { en: "Language", zh: "语言" },
    "appearance.lang.zh": { en: "中文", zh: "中文" },
    "appearance.lang.en": { en: "English", zh: "English" },
    "appearance.lang.bi": { en: "Bilingual (EN · 中文)", zh: "双语（先英后中）" },
    "appearance.density": { en: "Density", zh: "密度模式" },
    "appearance.density.comfortable": { en: "Comfortable", zh: "舒适" },
    "appearance.density.compact": { en: "Compact", zh: "紧凑" },
    "appearance.width": { en: "Message width", zh: "消息宽度档位" },
    "appearance.width.narrow": { en: "Narrow", zh: "窄" },
    "appearance.width.medium": { en: "Medium", zh: "中" },
    "appearance.width.wide": { en: "Wide", zh: "宽" },
    "appearance.saved": { en: "Appearance preferences saved", zh: "界面偏好已保存" },

    "skills.title": { en: "Skills", zh: "技能管理" },

    "thread.empty": { en: "No messages", zh: "暂无消息" },
    "thread.new": { en: "New chat", zh: "新对话" },
    "thread.delete": { en: "Delete chat", zh: "删除对话" },

    "confirm.allow": { en: "Allowed", zh: "已允许" },
    "confirm.deny": { en: "Denied", zh: "已拒绝" },
  };

  function getLanguage() {
    try {
      const raw = localStorage.getItem(UI_PREFS_KEY);
      if (!raw) return "bi";
      const parsed = JSON.parse(raw);
      const lang = parsed?.language;
      if (lang === "zh" || lang === "en" || lang === "bi") return lang;
      return "bi";
    } catch (_error) {
      return "bi";
    }
  }

  function t(key, vars) {
    const item = STRINGS[key];
    if (!item) return key;
    const lang = getLanguage();
    let text;
    if (lang === "en") {
      text = item.en;
    } else if (lang === "zh") {
      text = item.zh;
    } else {
      text = `${item.en} · ${item.zh}`;
    }
    if (vars && typeof vars === "object") {
      for (const [name, value] of Object.entries(vars)) {
        text = text.replaceAll(`{${name}}`, String(value));
      }
    }
    return text;
  }

  function applyDocument(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (key) el.textContent = t(key);
    });
    scope.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      const key = el.getAttribute("data-i18n-placeholder");
      if (key) el.placeholder = t(key);
    });
    scope.querySelectorAll("[data-i18n-title]").forEach((el) => {
      const key = el.getAttribute("data-i18n-title");
      if (key) el.title = t(key);
    });
    scope.querySelectorAll("[data-i18n-aria]").forEach((el) => {
      const key = el.getAttribute("data-i18n-aria");
      if (key) el.setAttribute("aria-label", t(key));
    });
    scope.querySelectorAll("[data-i18n-prompt]").forEach((el) => {
      const key = el.getAttribute("data-i18n-prompt");
      if (key) el.dataset.prompt = STRINGS[key]?.zh || STRINGS[key]?.en || "";
    });
    const lang = getLanguage();
    document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
    document.title = t("app.title");
  }

  window.LuminaI18n = {
    t,
    getLanguage,
    applyDocument,
    STRINGS,
  };
})();
