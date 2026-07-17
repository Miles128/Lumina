(function () {
  "use strict";

  const UI_PREFS_KEY = "lumina.ui.preferences.v1";

  const STRINGS = {
    "app.name": { en: "Lumina", zh: "灵犀" },
    "app.title": { en: "Lumina", zh: "灵犀" },

    "menu.skills": { en: "Skills", zh: "技能" },
    "menu.settings": { en: "Settings", zh: "设置" },
    "menu.knowledge": { en: "Knowledge", zh: "知识库" },
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
    "chat.welcome": { en: "What to build today?", zh: "今天做点什么？" },
    "chat.placeholder": { en: "Message", zh: "输入消息" },
    "chat.processing": { en: "Working…", zh: "正在处理…" },
    "chat.thinking": { en: "Thinking", zh: "思考中" },
    "chat.typing.understand": { en: "Understanding your question…", zh: "正在理解你的问题…" },
    "chat.typing.gather": { en: "Gathering relevant info…", zh: "正在整理相关信息…" },
    "chat.typing.tools": { en: "Running tools…", zh: "正在调用工具处理…" },
    "chat.typing.almost": { en: "Almost done…", zh: "还在继续处理，马上给你结果…" },
    "chat.typing.slow": { en: "This is taking a while — tap Pause to stop.", zh: "这次耗时较长，你可以点「暂停」先中止。" },
    "chat.typing.organize": { en: "Preparing reply…", zh: "正在整理回复…" },
    "chat.typing.execute": { en: "Executing…", zh: "正在执行操作…" },
    "chat.typing.subagent": { en: "Spawning sub-agent…", zh: "正在派生子 Agent…" },
    "chat.progress.thought": { en: "Reasoning", zh: "思考" },
    "chat.progress.toggle": { en: "Thinking", zh: "思考与原文" },
    "chat.progress.toggle.thinking": { en: "Thinking", zh: "查看思考" },
    "chat.progress.toggle.raw": { en: "Raw", zh: "查看原文" },
    "chat.progress.toggle.steps": {
      en: "Thinking · {n}",
      zh: "思考与原文 · {n} 步",
    },
    "chat.progress.raw": { en: "Raw", zh: "模型原文" },
    "chat.confirm.subagent": { en: "Sub-agent action", zh: "子 Agent 操作" },
    "chat.turn.root": { en: "Current turn", zh: "当前回合" },
    "chat.subagent.running": { en: "Running", zh: "运行中" },
    "chat.subagent.paused": { en: "Awaiting confirmation", zh: "等待确认" },
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
    "token.label": { en: "Token", zh: "Token" },
    "model.unset": { en: "No model", zh: "未指定模型" },
    "model.unconfigured": { en: "Not configured", zh: "未配置模型" },
    "model.current": { en: "Current model", zh: "当前大模型" },
    "token.usage": { en: "Total token usage", zh: "累计 token 消耗" },

    "settings.title": { en: "Settings", zh: "设置" },
    "settings.loading": { en: "Loading…", zh: "加载中…" },
    "settings.loadFailed": { en: "Failed to load", zh: "加载失败" },
    "settings.agent": { en: "Agent", zh: "Agent" },
    "settings.knowledge": { en: "Knowledge & Sync", zh: "知识库与同步" },
    "settings.personal": { en: "Personal", zh: "个人" },
    "settings.group.agent": { en: "Agent", zh: "Agent" },
    "settings.group.tools": { en: "Tools & Extensions", zh: "工具与扩展" },
    "settings.group.knowledge": { en: "Knowledge", zh: "知识库" },
    "settings.group.personal": { en: "Personal", zh: "个人" },
    "settings.skills": { en: "Skills", zh: "技能" },
    "settings.skills.openManager": { en: "Open Skills Manager", zh: "打开技能管理" },
    "settings.about": { en: "About", zh: "关于" },
    "settings.profile": { en: "Profile", zh: "个人画像" },
    "settings.llm": { en: "LLM", zh: "大模型" },
    "settings.soul": { en: "SOUL", zh: "人格 SOUL" },
    "settings.memory": { en: "Memory", zh: "持久记忆" },
    "settings.mcp": { en: "MCP Tools", zh: "MCP 工具" },
    "settings.mcp.connected": { en: "Connected", zh: "已连接" },
    "settings.mcp.disconnected": { en: "Not connected", zh: "未连接" },
    "settings.mcp.disabled": { en: "Disabled", zh: "已禁用" },
    "settings.mcp.empty": { en: "No MCP servers configured", zh: "尚未配置 MCP 服务器" },
    "settings.mcp.emptyVoice": {
      en: "No MCP servers yet. Start with local files, then add more tools when needed.",
      zh: "还没有 MCP 服务器。先接入本地文件，再按需扩展工具。",
    },
    "settings.mcp.emptyAction": { en: "Add Filesystem quickstart", zh: "添加 Filesystem 快速开始" },
    "settings.mcp.delete": { en: "Remove", zh: "删除" },
    "settings.mcp.deleteConfirm": {
      en: "Remove MCP server “{name}”? This cannot be undone.",
      zh: "确定删除 MCP 服务器「{name}」吗？",
    },
    "settings.mcp.deleting": { en: "Removing MCP server…", zh: "正在删除 MCP 服务器…" },
    "settings.mcp.deleted": { en: "Removed {name}", zh: "已删除 {name}" },
    "settings.mcp.deleteFailed": { en: "Remove failed: {error}", zh: "删除失败：{error}" },
    "settings.mcp.reloading": { en: "Reconnecting MCP…", zh: "正在重新连接 MCP…" },
    "settings.mcp.reloaded": { en: "Loaded {count} MCP tools", zh: "已加载 {count} 个 MCP 工具" },
    "settings.mcp.reloadFailed": { en: "Connection failed: {error}", zh: "连接失败：{error}" },
    "settings.shibei": { en: "Shibei KB", zh: "Shibei 知识库" },
    "settings.appearance": { en: "Appearance", zh: "界面" },

    "appearance.title": { en: "Appearance", zh: "界面" },
    "appearance.desc": {
      en: "Theme, density, reading width, and display language.",
      zh: "调整主题、密度、阅读宽度与界面语言。",
    },
    "appearance.theme": { en: "Theme", zh: "主题" },
    "appearance.theme.system": { en: "System", zh: "跟随系统" },
    "appearance.theme.light": { en: "White", zh: "白" },
    "appearance.theme.dark": { en: "Black", zh: "黑" },
    "appearance.theme.paper": { en: "Paper", zh: "纸" },
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

    "map.title": { en: "Conversation map", zh: "对话地图" },
    "map.hint": { en: "Click a node to switch branch", zh: "点击节点切换分支" },
    "map.empty": { en: "No conversation nodes", zh: "暂无对话节点" },
    "map.switching": { en: "Switching branch…", zh: "正在切换分支…" },
    "map.switchFailed": { en: "Switch failed: {error}", zh: "切换失败：{error}" },
    "map.retry": { en: "Please retry later", zh: "请稍后重试" },
    "map.placeholder.question": { en: "(question)", zh: "(提问)" },
    "map.placeholder.answer": { en: "(Lumina)", zh: "(灵犀)" },
    "map.placeholder.pending": { en: "(pending)", zh: "（待回答）" },
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
