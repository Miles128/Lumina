(function () {
  "use strict";

  const UI_PREFS_KEY = "lumina.ui.preferences.v1";

  const STRINGS = {
    "app.name": { en: "Lumina", zh: "灵犀" },
    "app.title": { en: "Lumina", zh: "灵犀" },

    "menu.skills": { en: "Skills", zh: "技能" },
    "menu.workflows": { en: "Workflows", zh: "工作流" },
    "menu.settings": { en: "Settings", zh: "设置" },
    "menu.knowledge": { en: "Knowledge", zh: "知识库" },
    "menu.about": { en: "About", zh: "关于" },

    "workflows.title": { en: "Workflows", zh: "工作流" },
    "workflows.empty": {
      en: "No workflows yet. Create a sample to open the canvas.",
      zh: "暂无工作流。新建示例即可打开画布。",
    },
    "workflows.newSample": { en: "New sample", zh: "新建示例" },
    "workflows.save": { en: "Save", zh: "保存" },
    "workflows.run": { en: "Run", zh: "运行" },
    "workflows.delete": { en: "Delete", zh: "删除" },
    "workflows.inputs": { en: "Run inputs (JSON)", zh: "运行输入（JSON）" },
    "workflows.result": { en: "Result", zh: "运行结果" },
    "workflows.nodes": { en: "Nodes", zh: "节点" },
    "workflows.palette": { en: "Add node", zh: "添加节点" },
    "workflows.selectNode": { en: "Select a node to edit", zh: "选中节点以编辑" },
    "workflows.canvasHint": {
      en: "Drag to pan · connect ports · save before run.",
      zh: "拖动画布平移 · 端口连线 · 运行前先保存。",
    },
    "workflows.deleteConfirm": { en: "Delete this workflow?", zh: "删除该工作流？" },
    "workflows.saved": { en: "Saved", zh: "已保存" },

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
    "chat.fullFsAccess": { en: "Full access", zh: "完全权限" },
    "chat.fullFsAccess.tip": {
      en: "Off = writes stay in the current workspace/sandbox. On = agent may write anywhere (still may confirm).",
      zh: "关闭时仅可写当前工作区/会话沙箱；开启后可写任意路径（仍可能需要确认）。",
    },
    "chat.fullFsAccess.on": {
      en: "Full filesystem access enabled",
      zh: "已开启完全权限（可写沙箱外）",
    },
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
    "chat.progress.stepExpandHint": {
      en: "Click a step to expand",
      zh: "点击某一步可展开详情",
    },
    "chat.progress.command": { en: "Command", zh: "命令" },
    "chat.progress.action": { en: "Action", zh: "动作" },
    "chat.progress.output": { en: "Output", zh: "输出" },
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
    "settings.knowledge": { en: "Knowledge", zh: "知识库" },
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
    "settings.delegation": { en: "Delegation & confirm", zh: "委派与确认" },
    "settings.delegation.desc": {
      en: "Choose a permission preset (normal / auto / yolo), then fine-tune which actions still require confirmation. Profile and archetype tables below are read-only.",
      zh: "选择权限档位（normal / auto / yolo），再细调哪些操作仍需确认。下方 Profile / Archetype 表为只读说明。",
    },
    "settings.delegation.saved": {
      en: "Permission policy saved",
      zh: "权限策略已保存",
    },
    "settings.delegation.mode": { en: "Permission mode", zh: "权限档位" },
    "settings.delegation.mode.normal": {
      en: "normal — confirm all risky actions",
      zh: "normal · 危险操作均需确认",
    },
    "settings.delegation.mode.auto": {
      en: "auto — skip new-file write & code_exec",
      zh: "auto · 新建文件与 code_exec 免确认",
    },
    "settings.delegation.mode.yolo": {
      en: "yolo — skip most confirmations (dangerous)",
      zh: "yolo · 几乎不确认（危险）",
    },
    "settings.delegation.mode.custom": {
      en: "custom — fine-tuned kinds",
      zh: "custom · 自定义细粒度",
    },
    "settings.delegation.yoloWarn": {
      en: "Yolo disables write/shell/action confirmations and grants permanent read. Use only in trusted local workspaces.",
      zh: "Yolo 会关闭写/Shell/其他操作确认，并开启永久读授权。仅在可信本地工作区使用。",
    },
    "settings.delegation.requireConfirm": {
      en: "Require confirmation for",
      zh: "需确认的操作",
    },
    "settings.delegation.kind.write_new": { en: "New file write", zh: "新建文件写入" },
    "settings.delegation.kind.write_modify": { en: "Modify existing file", zh: "修改已有文件" },
    "settings.delegation.kind.write_delete": { en: "Delete file", zh: "删除文件" },
    "settings.delegation.kind.shell": { en: "Non-readonly shell", zh: "非只读 Shell" },
    "settings.delegation.kind.action": {
      en: "Other writes / code_exec / MCP",
      zh: "其他写操作 / code_exec / MCP",
    },
    "settings.delegation.grants": { en: "Session grants", zh: "当前会话授权" },
    "settings.delegation.grant.permanent_read": {
      en: "Permanent read grant",
      zh: "永久读授权",
    },
    "settings.delegation.grant.session_write_new": {
      en: "Session: new-file write without confirm",
      zh: "本会话新建文件免确认",
    },
    "settings.delegation.grant.session_code_exec": {
      en: "Session: code_exec without confirm",
      zh: "本会话 code_exec 免确认",
    },
    "settings.delegation.profiles": { en: "Primary profiles", zh: "主会话 Profile" },
    "settings.delegation.archetypes": { en: "Sub-agent archetypes", zh: "子 Agent Archetype" },
    "settings.delegation.notes": { en: "Notes", zh: "说明" },
    "settings.delegation.limits": {
      en: "Sub-agent depth cap: {depth} · max spawns/turn: {spawns} · parallel explore: {explore}",
      zh: "子 Agent 深度上限：{depth} · 每轮最多 spawn：{spawns} · 并行 explore：{explore}",
    },
    "settings.harness": { en: "Harness", zh: "Harness 参数" },
    "settings.harness.desc": {
      en: "Tune loop budget, compaction, and reasoning-trace retention. Defaults are safe; advanced knobs for controlled environments.",
      zh: "调整工具轮次、上下文压缩与思考链保留策略。默认安全合理；企业可控环境可细调。",
    },
    "settings.harness.saved": { en: "Harness settings saved", zh: "Harness 参数已保存" },
    "settings.harness.max_tool_rounds": {
      en: "Max tool rounds",
      zh: "最大工具轮次",
    },
    "settings.harness.light_max_steps": {
      en: "Light profile max steps",
      zh: "轻量模式最大步数",
    },
    "settings.harness.compaction_max_tokens": {
      en: "Compaction token budget",
      zh: "压缩触发 token 上限",
    },
    "settings.harness.compaction_keep_tail": {
      en: "Compaction keep-tail messages",
      zh: "压缩后保留尾部消息数",
    },
    "settings.harness.trace_retention": {
      en: "Trace retention",
      zh: "思考链保留策略",
    },
    "settings.harness.trace_retention.full": { en: "full", zh: "完整" },
    "settings.harness.trace_retention.summary": { en: "summary", zh: "摘要" },
    "settings.harness.trace_retention.off": { en: "off", zh: "关闭" },
    "settings.harness.trace_retain_days": {
      en: "Trace retain days",
      zh: "思考链保留天数",
    },
    "settings.harness.max_tool_output_chars": {
      en: "Max tool output chars",
      zh: "工具输出最大字符数",
    },
    "settings.harness.thinking_mode": {
      en: "Thinking mode (DeepSeek)",
      zh: "思考模式（DeepSeek）",
    },
    "settings.harness.thinking_mode.auto": {
      en: "auto — off in DIRECT / on in Agent",
      zh: "auto · DIRECT 关 / Agent 开",
    },
    "settings.harness.thinking_mode.enabled": {
      en: "enabled — always on",
      zh: "enabled · 始终开启",
    },
    "settings.harness.thinking_mode.disabled": {
      en: "disabled — always off",
      zh: "disabled · 始终关闭",
    },
    "settings.harness.reasoning_effort": {
      en: "Reasoning effort (Agent)",
      zh: "推理强度（Agent）",
    },
    "settings.harness.reasoning_effort.low": { en: "low", zh: "低" },
    "settings.harness.reasoning_effort.high": {
      en: "high (default)",
      zh: "high（默认）",
    },
    "settings.harness.reasoning_effort.max": { en: "max", zh: "最大" },
    "settings.harness.strict_tools": {
      en: "Strict tools (DeepSeek beta)",
      zh: "严格工具调用（DeepSeek beta）",
    },
    "settings.harness.group.loop": {
      en: "Loop & compaction",
      zh: "循环与压缩",
    },
    "settings.harness.group.thinking": {
      en: "Thinking",
      zh: "思考",
    },
    "settings.harness.group.runtime": {
      en: "Runtime",
      zh: "运行时",
    },
    "settings.harness.group.observability": {
      en: "Observability",
      zh: "可观测",
    },
    "settings.harness.runtime_backend": {
      en: "Agent runtime backend",
      zh: "Agent 运行时后端",
    },
    "settings.harness.runtime_backend.agents_sdk": {
      en: "OpenAI Agents SDK (default)",
      zh: "OpenAI Agents SDK（默认）",
    },
    "settings.harness.runtime_backend.aisuite": {
      en: "aisuite Runner",
      zh: "aisuite Runner",
    },
    "settings.harness.runtime_backend.legacy": {
      en: "legacy AgentLoop",
      zh: "legacy AgentLoop",
    },
    "settings.harness.web_search_backend": {
      en: "Web search backend",
      zh: "联网搜索后端",
    },
    "settings.harness.web_search_backend.tavily": {
      en: "Tavily / self-hosted API",
      zh: "Tavily / 自研 API",
    },
    "settings.harness.web_search_backend.responses": {
      en: "DeepSeek built-in (Responses)",
      zh: "DeepSeek 内置（Responses）",
    },
    "settings.harness.crosslinks": {
      en: "History turns: Settings → LLM. Permission mode: Settings → Delegation.",
      zh: "历史轮数见「LLM」；权限模式见「委派与确认」。",
    },
    "settings.harness.footer": {
      en: "Sub-agent depth hard-limit is depth=1 and cannot be bypassed. See Delegation & confirm.",
      zh: "子 Agent 深度硬限 depth=1 不可配置绕过。委派说明见「委派与确认」。",
    },
    "chat.progress.exportTrace": { en: "Export trace", zh: "导出思考链" },
    "chat.progress.loadTrace": { en: "Reload trace", zh: "加载轨迹" },
    "workflows.fromTemplate": { en: "From template", zh: "从模板" },
    "workflows.approve": { en: "Approve & continue", zh: "通过并继续" },
    "workflows.reject": { en: "Reject", zh: "拒绝" },
    "workflows.noTemplates": { en: "No templates installed", zh: "没有可用模板" },
    "workflows.pickTemplate": { en: "Pick a template number:", zh: "输入模板序号：" },
    "workflows.templateName": { en: "Workflow name", zh: "工作流名称" },
    "settings.soul": { en: "SOUL", zh: "身份 SOUL" },
    "chat.progress.metrics": {
      en: "Tools {tools} · Subagents {subs} · Compaction {comp}",
      zh: "工具 {tools} · 子Agent {subs} · 压缩 {comp}",
    },
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
    "confirm.btn.allow": { en: "Allow", zh: "允许" },
    "confirm.btn.deny": { en: "Deny", zh: "拒绝" },
    "confirm.btn.once": { en: "Allow once", zh: "仅本次" },
    "confirm.btn.sessionWrite": { en: "Allow new files this session", zh: "本次可新建文件" },

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
