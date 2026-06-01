(function () {
  "use strict";

  const panel = document.getElementById("settings-panel");
  const backdrop = document.getElementById("settings-backdrop");
  const navEl = document.getElementById("settings-nav");
  const contentEl = document.getElementById("settings-content");

  let platforms = [];
  let profileMarkdown = "";
  let profileAutoMarkdown = "";
  let profileIsUserEdited = false;
  let activeKey = "agent_llm";
  let agentConfig = null;
  let agentSoul = "";
  let agentSoulPath = "";
  let durableMemoryMd = "";
  let durableUserMd = "";
  let uiPreferences = { density: "comfortable", messageWidth: "medium", language: "bi" };
  let mcpStatus = null;
  let backgroundTasks = null;

  function t(key, vars) {
    if (window.LuminaI18n) {
      return window.LuminaI18n.t(key, vars);
    }
    return key;
  }

  document.getElementById("btn-platforms").addEventListener("click", () => openSettings());
  document.getElementById("btn-close-settings").addEventListener("click", closeSettings);
  backdrop.addEventListener("click", closeSettings);

  window.addEventListener("lumina:language", () => {
    if (panel.hidden) return;
    renderNav();
    renderContent(activeKey);
    window.LuminaI18n?.applyDocument(panel);
  });

  async function openSettings(preferredKey) {
    panel.hidden = false;
    backdrop.hidden = false;
    if (preferredKey) {
      activeKey = preferredKey;
    }
    try {
      await loadSettings();
    } catch (error) {
      contentEl.innerHTML = `<p class="muted">${escapeHtml(t("settings.loadFailed"))}：${escapeHtml(error.message)}</p>`;
    }
  }

  function closeSettings() {
    panel.hidden = true;
    backdrop.hidden = true;
  }

  async function loadSettings() {
    contentEl.innerHTML = `<p class="muted">${escapeHtml(t("settings.loading"))}</p>`;
    const [platformList, profile, config, soul, durable, mcp, background] = await Promise.all([
      window.SecretaryAPI.request("GET", "/api/settings/platforms"),
      window.SecretaryAPI.request("GET", "/api/profile"),
      window.SecretaryAPI.request("GET", "/api/agent/config"),
      window.SecretaryAPI.request("GET", "/api/agent/soul"),
      window.SecretaryAPI.request("GET", "/api/memory/durable"),
      window.SecretaryAPI.request("GET", "/api/mcp/status").catch(() => null),
      window.SecretaryAPI.request("GET", "/api/agent/background").catch(() => null),
    ]);
    platforms = platformList;
    agentConfig = config;
    agentSoul = soul.markdown || "";
    agentSoulPath = soul.path || "";
    durableMemoryMd = durable.memory_md || "";
    durableUserMd = durable.user_md || "";
    mcpStatus = mcp;
    backgroundTasks = background;
    uiPreferences = loadUiPreferences();
    profileMarkdown = profile.markdown || "";
    profileAutoMarkdown = profile.auto_markdown || profile.markdown || "";
    profileIsUserEdited = Boolean(profile.is_user_edited);
    if (
      !platforms.some((item) => item.source === activeKey) &&
      !["profile", "agent_llm", "agent_soul", "agent_memory", "agent_mcp", "appearance"].includes(activeKey)
    ) {
      activeKey = "agent_llm";
    }
    renderNav();
    renderContent(activeKey);
  }

  function renderNav() {
    navEl.innerHTML = "";

    const agentGroup = document.createElement("div");
    agentGroup.className = "settings-nav-group";
    agentGroup.innerHTML = `<div class="settings-nav-label">${escapeHtml(t("settings.agent"))}</div>`;

    for (const item of [
      { key: "agent_llm", label: t("settings.llm"), status: agentConfig?.status || "not_configured" },
      { key: "agent_soul", label: t("settings.soul"), status: "ready" },
      { key: "agent_memory", label: t("settings.memory"), status: "ready" },
      { key: "agent_mcp", label: t("settings.mcp"), status: mcpStatus?.tool_count ? "ready" : "not_configured" },
      { key: "appearance", label: t("settings.appearance"), status: "ready" },
    ]) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `settings-nav-item${activeKey === item.key ? " active" : ""}`;
      btn.dataset.key = item.key;
      btn.innerHTML = `
        <span>${escapeHtml(item.label)}</span>
        <span class="status-dot ${item.status}" aria-hidden="true"></span>
      `;
      btn.addEventListener("click", () => selectTab(item.key));
      agentGroup.appendChild(btn);
    }
    navEl.appendChild(agentGroup);

    const sourceGroup = document.createElement("div");
    sourceGroup.className = "settings-nav-group";
    sourceGroup.innerHTML = `<div class="settings-nav-label">${escapeHtml(t("settings.sources"))}</div>`;

    for (const platform of platforms) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `settings-nav-item${platform.source === activeKey ? " active" : ""}`;
      btn.dataset.key = platform.source;
      btn.innerHTML = `
        <span>${escapeHtml(platform.name)}</span>
        <span class="status-dot ${platform.status}" aria-hidden="true"></span>
      `;
      btn.addEventListener("click", () => selectTab(platform.source));
      sourceGroup.appendChild(btn);
    }
    navEl.appendChild(sourceGroup);

    const profileBtn = document.createElement("button");
    profileBtn.type = "button";
    profileBtn.className = `settings-nav-item${activeKey === "profile" ? " active" : ""}`;
    profileBtn.dataset.key = "profile";
    profileBtn.innerHTML = `<span>${escapeHtml(t("settings.profile"))}</span>`;
    profileBtn.addEventListener("click", () => selectTab("profile"));
    navEl.appendChild(profileBtn);
  }

  function selectTab(key) {
    activeKey = key;
    navEl.querySelectorAll(".settings-nav-item").forEach((item) => {
      item.classList.toggle("active", item.dataset.key === key);
    });
    renderContent(key);
  }

  function renderContent(key) {
    if (key === "agent_llm") {
      renderAgentLlmPane();
      return;
    }
    if (key === "agent_soul") {
      renderAgentSoulPane();
      return;
    }
    if (key === "agent_memory") {
      renderAgentMemoryPane();
      return;
    }
    if (key === "agent_mcp") {
      renderAgentMcpPane();
      return;
    }
    if (key === "profile") {
      contentEl.innerHTML = `
        <div class="settings-pane profile-edit-pane">
          <header class="settings-pane-head">
            <h3>个人画像</h3>
            <p>可直接编辑。保存后以你的版本为准；自动摘要仅作参考，不会猜测或编造。</p>
          </header>
          <textarea id="profile-editor" class="profile-editor" rows="18">${escapeHtml(profileMarkdown)}</textarea>
          <div class="platform-actions">
            <button class="btn-text save-btn" type="button" id="btn-save-profile">保存</button>
            <button class="btn-text" type="button" id="btn-reset-profile">恢复自动摘要</button>
          </div>
          <div id="profile-feedback" class="platform-feedback" hidden></div>
        </div>
      `;
      document.getElementById("btn-save-profile").addEventListener("click", saveProfile);
      document.getElementById("btn-reset-profile").addEventListener("click", resetProfile);
      return;
    }
    if (key === "appearance") {
      renderAppearancePane();
      return;
    }

    const platform = platforms.find((item) => item.source === key);
    if (!platform) {
      contentEl.innerHTML = '<p class="muted">未找到该配置项</p>';
      return;
    }

    const pane = document.createElement("div");
    pane.className = "settings-pane";
    pane.dataset.source = platform.source;

    const fieldsHtml =
      platform.fields.length === 0
        ? `<p class="settings-hint">${escapeHtml(platform.setup_hint)}</p>`
        : `<div class="settings-fields">${platform.fields.map((field) => renderField(platform.source, field)).join("")}</div>`;

    pane.innerHTML = `
      <header class="settings-pane-head">
        <div class="settings-pane-title">
          <h3>${escapeHtml(platform.name)}</h3>
          <span class="platform-status ${platform.status}">${statusLabel(platform.status)}</span>
        </div>
        <p>${escapeHtml(platform.description)}</p>
      </header>
      ${fieldsHtml}
      <p class="platform-meta">${escapeHtml(platform.status_message)}</p>
      <div class="platform-actions">
        ${platform.fields.length > 0 ? '<button class="btn-text save-btn" type="button" data-action="save">保存</button>' : ""}
        <button class="btn-text test-btn" type="button" data-action="test">测试连接</button>
      </div>
      <div class="platform-feedback" hidden></div>
    `;

    const saveBtn = pane.querySelector('[data-action="save"]');
    if (saveBtn) {
      saveBtn.addEventListener("click", () => savePlatform(platform.source, pane));
    }
    pane.querySelector('[data-action="test"]').addEventListener("click", () => testPlatform(platform.source, pane));
    contentEl.innerHTML = "";
    contentEl.appendChild(pane);
  }

  function renderField(source, field) {
    const id = `${source}-${field.key}`;
    if (field.field_type === "checkbox") {
      const checked = field.value === true || field.value === "true";
      return `
        <label class="settings-field settings-field-check" for="${id}">
          <input id="${id}" data-key="${field.key}" type="checkbox"${checked ? " checked" : ""} />
          <span>${escapeHtml(field.label)}</span>
        </label>
      `;
    }

    const input =
      field.field_type === "textarea"
        ? `<textarea id="${id}" data-key="${field.key}" rows="5" placeholder="${escapeAttr(field.placeholder)}">${escapeHtml(String(field.value || ""))}</textarea>`
        : `<input id="${id}" data-key="${field.key}" type="${field.field_type === "password" ? "password" : field.field_type === "number" ? "number" : "text"}" value="${escapeAttr(String(field.value ?? ""))}" placeholder="${escapeAttr(field.placeholder)}" />`;

    return `
      <label class="settings-field" for="${id}">
        <span>${escapeHtml(field.label)}</span>
        ${input}
      </label>
    `;
  }

  function collectValues(pane) {
    const values = {};
    pane.querySelectorAll("[data-key]").forEach((element) => {
      const key = element.dataset.key;
      if (!key) return;
      if (element.tagName === "TEXTAREA") {
        values[key] = element.value;
        return;
      }
      if (element.type === "checkbox") {
        values[key] = element.checked;
        return;
      }
      if (element.type === "number") {
        values[key] = Number(element.value || 0);
        return;
      }
      values[key] = element.value;
    });
    return values;
  }

  async function savePlatform(source, pane) {
    const feedback = pane.querySelector(".platform-feedback");
    try {
      const updated = await window.SecretaryAPI.request("PUT", `/api/settings/platforms/${source}`, {
        values: collectValues(pane),
      });
      showFeedback(feedback, "success", "已保存");
      updatePaneStatus(pane, source, updated.status, updated.status_message);
    } catch (error) {
      showFeedback(feedback, "error", `保存失败：${error.message}`);
    }
  }

  async function testPlatform(source, pane) {
    const feedback = pane.querySelector(".platform-feedback");
    showFeedback(feedback, "info", "测试中…");
    try {
      const saveBtn = pane.querySelector('[data-action="save"]');
      if (saveBtn) {
        await window.SecretaryAPI.request("PUT", `/api/settings/platforms/${source}`, {
          values: collectValues(pane),
        });
      }
      const result = await window.SecretaryAPI.request("POST", `/api/settings/platforms/${source}/test`);
      const message =
        source === "local_documents" || Number(result.inserted) === 0
          ? result.message
          : `${result.message}（写入 ${result.inserted} 条）`;
      showFeedback(feedback, result.status === "ready" ? "success" : "error", message);
      updatePaneStatus(pane, source, result.status, result.message);
    } catch (error) {
      showFeedback(feedback, "error", `测试失败：${error.message}`);
    }
  }

  function updatePaneStatus(pane, source, status, message) {
    const badge = pane.querySelector(".platform-status");
    badge.className = `platform-status ${status}`;
    badge.textContent = statusLabel(status);
    pane.querySelector(".platform-meta").textContent = message;

    const platform = platforms.find((item) => item.source === source);
    if (platform) {
      platform.status = status;
      platform.status_message = message;
    }
    const navItem = navEl.querySelector(`.settings-nav-item[data-key="${source}"] .status-dot`);
    if (navItem) {
      navItem.className = `status-dot ${status}`;
    }
  }

  function notifyAgentConfig(config) {
    window.dispatchEvent(
      new CustomEvent("lumina:agent-config", {
        detail: { model: config?.model || "", status: config?.status || "" },
      }),
    );
  }

  function showFeedback(element, kind, text) {
    element.hidden = false;
    element.className = `platform-feedback ${kind}`;
    element.textContent = text;
  }

  function renderAgentLlmPane() {
    const cfg = agentConfig || {};
    const responseStyle = cfg.response_style || "standard";
    const providerOptions = (cfg.providers || [])
      .map(
        (item) =>
          `<option value="${escapeAttr(item.key)}"${item.key === cfg.provider ? " selected" : ""}>${escapeHtml(item.label)}</option>`,
      )
      .join("");

    contentEl.innerHTML = `
      <div class="settings-pane">
        <header class="settings-pane-head">
          <div class="settings-pane-title">
            <h3>大模型</h3>
            <span class="platform-status ${escapeAttr(cfg.status || "not_configured")}">${statusLabel(cfg.status || "not_configured")}</span>
          </div>
          <p>配置 OpenAI 兼容 API。若 Hermes config.yaml 里是 sk-990...7755 这种脱敏占位符，会自动改读 ~/.hermes/.env 里的真实 Key。</p>
        </header>
        <p class="platform-meta">${escapeHtml(cfg.status_message || "")}</p>
        <div class="settings-fields">
          <label class="settings-field">
            <span>提供商</span>
            <select id="agent-provider">${providerOptions}</select>
          </label>
          <label class="settings-field">
            <span>API Key</span>
            <input id="agent-api-key" type="password" value="" placeholder="${escapeAttr(cfg.api_key_masked || "sk-...")}" />
          </label>
          <label class="settings-field">
            <span>Base URL</span>
            <input id="agent-base-url" type="text" value="${escapeAttr(cfg.base_url || "")}" placeholder="https://api.deepseek.com/v1" />
          </label>
          <label class="settings-field">
            <span>模型</span>
            <input id="agent-model" type="text" value="${escapeAttr(cfg.model || "")}" placeholder="deepseek-chat" />
          </label>
          <label class="settings-field">
            <span>温度</span>
            <input id="agent-temperature" type="range" min="0" max="1.5" step="0.1" value="${escapeAttr(String(cfg.temperature ?? 0.7))}" />
          </label>
          <label class="settings-field">
            <span>上下文轮数</span>
            <input id="agent-history" type="number" min="2" max="64" value="${escapeAttr(String(cfg.max_history_turns ?? 16))}" />
          </label>
          <label class="settings-field settings-field-check">
            <input id="agent-hermes-fallback" type="checkbox"${cfg.use_hermes_fallback ? " checked" : ""} />
            <span>本地未配置时，回退读取 ~/.hermes/config.yaml</span>
          </label>
          <label class="settings-field">
            <span>默认语气档位</span>
            <select id="agent-response-style">
              <option value="standard"${responseStyle === "standard" ? " selected" : ""}>标准</option>
              <option value="brief"${responseStyle === "brief" ? " selected" : ""}>简短</option>
            </select>
          </label>
          <label class="settings-field">
            <span>Shell 工作目录 · Shell working dir</span>
            <input id="agent-shell-cwd" type="text" value="${escapeAttr(cfg.shell_working_dir || "")}" placeholder="留空则使用用户主目录" />
          </label>
        </div>
        <div class="platform-actions">
          <button class="btn-text save-btn" type="button" id="btn-save-agent">保存</button>
          <button class="btn-text test-btn" type="button" id="btn-test-agent">测试连接</button>
          <button class="btn-text" type="button" id="btn-import-hermes">从 Hermes 导入</button>
          <button class="btn-text" type="button" id="btn-clear-chat">清空对话历史</button>
        </div>
        <div id="agent-feedback" class="platform-feedback" hidden></div>
      </div>
    `;

    document.getElementById("btn-save-agent").addEventListener("click", saveAgentConfig);
    document.getElementById("btn-test-agent").addEventListener("click", testAgentConfig);
    document.getElementById("btn-import-hermes").addEventListener("click", importHermesConfig);
    document.getElementById("btn-clear-chat").addEventListener("click", clearChatHistory);
    document.getElementById("agent-provider").addEventListener("change", onProviderChange);
  }

  function onProviderChange(event) {
    const provider = event.target.value;
    const preset = (agentConfig?.providers || []).find((item) => item.key === provider);
    if (!preset || provider === "custom") return;
    const baseUrl = document.getElementById("agent-base-url");
    const model = document.getElementById("agent-model");
    if (baseUrl && preset.base_url) baseUrl.value = preset.base_url;
    if (model && preset.model) model.value = preset.model;
  }

  function collectAgentPayload() {
    return {
      provider: document.getElementById("agent-provider")?.value || "",
      api_key: document.getElementById("agent-api-key")?.value || "",
      base_url: document.getElementById("agent-base-url")?.value || "",
      model: document.getElementById("agent-model")?.value || "",
      temperature: Number(document.getElementById("agent-temperature")?.value || 0.7),
      max_history_turns: Number(document.getElementById("agent-history")?.value || 16),
      use_hermes_fallback: Boolean(document.getElementById("agent-hermes-fallback")?.checked),
      response_style: document.getElementById("agent-response-style")?.value || "standard",
      shell_working_dir: document.getElementById("agent-shell-cwd")?.value || "",
    };
  }

  function renderAppearancePane() {
    const density = uiPreferences.density || "comfortable";
    const width = uiPreferences.messageWidth || "medium";
    const language = uiPreferences.language || "bi";
    contentEl.innerHTML = `
      <div class="settings-pane">
        <header class="settings-pane-head">
          <h3>${escapeHtml(t("appearance.title"))}</h3>
          <p>${escapeHtml(t("appearance.desc"))}</p>
        </header>
        <div class="settings-fields">
          <label class="settings-field">
            <span>${escapeHtml(t("appearance.language"))}</span>
            <select id="ui-language">
              <option value="bi"${language === "bi" ? " selected" : ""}>${escapeHtml(t("appearance.lang.bi"))}</option>
              <option value="en"${language === "en" ? " selected" : ""}>${escapeHtml(t("appearance.lang.en"))}</option>
              <option value="zh"${language === "zh" ? " selected" : ""}>${escapeHtml(t("appearance.lang.zh"))}</option>
            </select>
          </label>
          <label class="settings-field">
            <span>${escapeHtml(t("appearance.density"))}</span>
            <select id="ui-density">
              <option value="comfortable"${density === "comfortable" ? " selected" : ""}>${escapeHtml(t("appearance.density.comfortable"))}</option>
              <option value="compact"${density === "compact" ? " selected" : ""}>${escapeHtml(t("appearance.density.compact"))}</option>
            </select>
          </label>
          <label class="settings-field">
            <span>${escapeHtml(t("appearance.width"))}</span>
            <select id="ui-message-width">
              <option value="narrow"${width === "narrow" ? " selected" : ""}>${escapeHtml(t("appearance.width.narrow"))}</option>
              <option value="medium"${width === "medium" ? " selected" : ""}>${escapeHtml(t("appearance.width.medium"))}</option>
              <option value="wide"${width === "wide" ? " selected" : ""}>${escapeHtml(t("appearance.width.wide"))}</option>
            </select>
          </label>
        </div>
        <div class="platform-actions">
          <button class="btn-text save-btn" type="button" id="btn-save-appearance">${escapeHtml(t("action.save"))}</button>
        </div>
        <div id="appearance-feedback" class="platform-feedback" hidden></div>
      </div>
    `;
    document.getElementById("btn-save-appearance").addEventListener("click", saveAppearance);
  }

  function saveAppearance() {
    const density = document.getElementById("ui-density")?.value || "comfortable";
    const messageWidth = document.getElementById("ui-message-width")?.value || "medium";
    const language = document.getElementById("ui-language")?.value || "bi";
    uiPreferences = { density, messageWidth, language };
    localStorage.setItem("lumina.ui.preferences.v1", JSON.stringify(uiPreferences));
    window.dispatchEvent(new CustomEvent("lumina:ui-preferences", { detail: uiPreferences }));
    window.dispatchEvent(new CustomEvent("lumina:language"));
    const feedback = document.getElementById("appearance-feedback");
    if (feedback) {
      showFeedback(feedback, "success", t("appearance.saved"));
    }
  }

  function loadUiPreferences() {
    try {
      const raw = localStorage.getItem("lumina.ui.preferences.v1");
      if (!raw) return { density: "comfortable", messageWidth: "medium", language: "bi" };
      const parsed = JSON.parse(raw);
      const density = parsed?.density === "compact" ? "compact" : "comfortable";
      const messageWidth = ["narrow", "medium", "wide"].includes(parsed?.messageWidth)
        ? parsed.messageWidth
        : "medium";
      const language = ["zh", "en", "bi"].includes(parsed?.language) ? parsed.language : "bi";
      return { density, messageWidth, language };
    } catch (_error) {
      return { density: "comfortable", messageWidth: "medium", language: "bi" };
    }
  }

  async function saveAgentConfig() {
    const feedback = document.getElementById("agent-feedback");
    try {
      agentConfig = await window.SecretaryAPI.request("PUT", "/api/agent/config", collectAgentPayload());
      notifyAgentConfig(agentConfig);
      showFeedback(feedback, "success", "已保存");
      renderNav();
    } catch (error) {
      showFeedback(feedback, "error", `保存失败：${error.message}`);
    }
  }

  async function testAgentConfig() {
    const feedback = document.getElementById("agent-feedback");
    showFeedback(feedback, "info", "测试中…");
    try {
      await window.SecretaryAPI.request("PUT", "/api/agent/config", collectAgentPayload());
      const result = await window.SecretaryAPI.request("POST", "/api/agent/config/test");
      agentConfig = await window.SecretaryAPI.request("GET", "/api/agent/config");
      notifyAgentConfig(agentConfig);
      showFeedback(feedback, "success", result.message);
      renderNav();
    } catch (error) {
      showFeedback(feedback, "error", `测试失败：${error.message}`);
    }
  }

  async function importHermesConfig() {
    const feedback = document.getElementById("agent-feedback");
    showFeedback(feedback, "info", "导入中…");
    try {
      agentConfig = await window.SecretaryAPI.request("POST", "/api/agent/config/import-hermes");
      notifyAgentConfig(agentConfig);
      showFeedback(feedback, "success", "已从 Hermes 导入，请点测试连接确认 Key 是否有效");
      renderContent("agent_llm");
      renderNav();
    } catch (error) {
      showFeedback(feedback, "error", `导入失败：${error.message}`);
    }
  }

  async function clearChatHistory() {
    const feedback = document.getElementById("agent-feedback");
    try {
      await window.SecretaryAPI.request("DELETE", "/api/chat/history");
      showFeedback(feedback, "success", "对话历史已清空");
    } catch (error) {
      showFeedback(feedback, "error", `清空失败：${error.message}`);
    }
  }

  const SOUL_PRESETS = {
    default:
      '## Identity\n\nname: "灵犀"\nrole: "CN 本地个人 AI 秘书"\ntone: "直接、简洁、实用"\nlanguage: "zh-CN"\n',
    concise:
      '## Identity\n\nname: "灵犀"\nrole: "简洁助手"\ntone: "短句、结论先行、不铺垫"\nlanguage: "zh-CN"\n',
    creative:
      '## Identity\n\nname: "灵犀"\nrole: "创意搭档"\ntone: "有观点、敢给方案、表达生动"\nlanguage: "zh-CN"\n',
  };

  function renderAgentSoulPane() {
    contentEl.innerHTML = `
      <div class="settings-pane profile-edit-pane">
        <header class="settings-pane-head">
          <h3>人格 SOUL</h3>
          <p>对应 Hermes 的 SOUL.md。灵犀优先使用 ~/.lumina/SOUL.md，保存后立即生效。</p>
        </header>
        <p class="platform-meta">${escapeHtml(agentSoulPath)}</p>
        <div class="settings-fields">
          <label class="settings-field">
            <span>快速预设</span>
            <select id="soul-preset">
              <option value="">选择预设…</option>
              <option value="default">灵犀默认</option>
              <option value="concise">简洁助手</option>
              <option value="creative">创意助手</option>
            </select>
          </label>
        </div>
        <textarea id="soul-editor" class="profile-editor" rows="18">${escapeHtml(agentSoul)}</textarea>
        <div class="platform-actions">
          <button class="btn-text save-btn" type="button" id="btn-save-soul">保存</button>
          <button class="btn-text" type="button" id="btn-import-hermes-soul">从 Hermes 导入 SOUL</button>
        </div>
        <div id="soul-feedback" class="platform-feedback" hidden></div>
      </div>
    `;

    document.getElementById("btn-save-soul").addEventListener("click", saveAgentSoul);
    document.getElementById("btn-import-hermes-soul").addEventListener("click", importHermesSoul);
    document.getElementById("soul-preset").addEventListener("change", applySoulPreset);
  }

  function applySoulPreset(event) {
    const value = event.target.value;
    if (!value || !SOUL_PRESETS[value]) return;
    const editor = document.getElementById("soul-editor");
    if (editor) editor.value = SOUL_PRESETS[value];
  }

  async function saveAgentSoul() {
    const editor = document.getElementById("soul-editor");
    const feedback = document.getElementById("soul-feedback");
    if (!editor || !feedback) return;
    try {
      const updated = await window.SecretaryAPI.request("PUT", "/api/agent/soul", {
        markdown: editor.value,
      });
      agentSoul = updated.markdown;
      agentSoulPath = updated.path;
      showFeedback(feedback, "success", "SOUL 已保存");
    } catch (error) {
      showFeedback(feedback, "error", `保存失败：${error.message}`);
    }
  }

  async function importHermesSoul() {
    const feedback = document.getElementById("soul-feedback");
    showFeedback(feedback, "info", "读取 Hermes SOUL…");
    try {
      const payload = await window.SecretaryAPI.request("GET", "/api/agent/soul/hermes");
      const editor = document.getElementById("soul-editor");
      if (editor) editor.value = payload.markdown || "";
      showFeedback(feedback, "success", "已载入 Hermes SOUL，点保存写入灵犀");
    } catch (error) {
      showFeedback(feedback, "error", `导入失败：${error.message}`);
    }
  }

  function renderAgentMemoryPane() {
    const bg = backgroundTasks || {};
    const thinkInfo = bg.think_enabled
      ? `每 ${bg.think_interval_hours || 6} 小时 · 上次 ${bg.last_think_at ? escapeHtml(String(bg.last_think_at).slice(0, 16)) : "尚未运行"}`
      : "已关闭";
    const summaryInfo = bg.memory_summary_enabled
      ? `每天 ${bg.memory_summary_hour ?? 23}:00 · 上次 ${bg.last_summary_date ? escapeHtml(String(bg.last_summary_date)) : "尚未运行"}`
      : "已关闭";

    contentEl.innerHTML = `
      <div class="settings-pane profile-edit-pane">
        <header class="settings-pane-head">
          <h3>持久记忆</h3>
          <p>对应 Hermes 的 MEMORY.md 与 USER.md，每次对话开始时注入系统提示。Agent 也可通过 memory 工具自动更新。</p>
        </header>
        <div class="platform-meta">
          <p>后台思考：${thinkInfo}</p>
          <p>记忆摘要：${summaryInfo}</p>
        </div>
        <label class="settings-field" for="durable-memory-editor">
          <span>MEMORY.md（环境与项目事实，最多 2200 字）</span>
          <textarea id="durable-memory-editor" class="profile-editor" rows="10">${escapeHtml(durableMemoryMd)}</textarea>
        </label>
        <label class="settings-field" for="durable-user-editor">
          <span>USER.md（用户偏好与画像，最多 1375 字）</span>
          <textarea id="durable-user-editor" class="profile-editor" rows="8">${escapeHtml(durableUserMd)}</textarea>
        </label>
        <div class="platform-actions">
          <button class="btn-text save-btn" type="button" id="btn-save-durable-memory">保存</button>
        </div>
        <div id="durable-memory-feedback" class="platform-feedback" hidden></div>
      </div>
    `;
    document.getElementById("btn-save-durable-memory").addEventListener("click", saveDurableMemory);
  }

  function renderAgentMcpPane() {
    const status = mcpStatus || {};
    const tools = Array.isArray(status.tools) ? status.tools : [];
    const servers = Array.isArray(status.servers) ? status.servers : [];
    const configPath = status.config_path || "~/.lumina/mcp.json";
    const toolRows = tools.length
      ? tools
          .map(
            (tool) =>
              `<tr><td>${escapeHtml(tool.name || "")}</td><td>${escapeHtml(tool.server || "")}</td><td>${escapeHtml(String(tool.description || "").slice(0, 120))}</td></tr>`,
          )
          .join("")
      : `<tr><td colspan="3" class="muted">暂无已连接的 MCP 工具</td></tr>`;
    const serverRows = servers.length
      ? servers
          .map(
            (server) =>
              `<li><strong>${escapeHtml(server.name || "")}</strong> · ${server.connected ? "已连接" : "未连接"} · ${escapeHtml(server.transport || "stdio")}</li>`,
          )
          .join("")
      : "<li class=\"muted\">尚未配置 MCP 服务器</li>";

    contentEl.innerHTML = `
      <div class="settings-pane">
        <header class="settings-pane-head">
          <h3>MCP 工具</h3>
          <p>外部 MCP 服务器提供的工具，对话时 Agent 可直接调用。配置文件：<code>${escapeHtml(configPath)}</code></p>
        </header>
        <p class="platform-meta">已加载 ${Number(status.tool_count || 0)} 个工具 · SDK ${status.available ? "可用" : "不可用"}</p>
        <p class="platform-meta muted">需要 Node.js / npx · 仅支持 stdio 传输（URL 暂不可用）· 写入类 MCP 工具需用户确认</p>
        ${status.last_error ? `<p class="platform-feedback error">${escapeHtml(status.last_error)}</p>` : ""}

        <h4 class="settings-subtitle">快速添加 · Quick start</h4>
        <div class="platform-actions">
          <button class="btn-text save-btn" type="button" id="btn-mcp-quickstart-fs">Filesystem MCP · 文件系统</button>
        </div>
        <label class="settings-field">
          <span>Filesystem 根目录（可选，默认 ~/Documents）</span>
          <input id="mcp-fs-root" type="text" placeholder="/Users/you/Documents" />
        </label>

        <h4 class="settings-subtitle">添加 MCP 服务器</h4>
        <div class="mcp-import-form">
          <label class="settings-field">
            <span>名称（英文，如 filesystem）</span>
            <input id="mcp-name" type="text" placeholder="filesystem" />
          </label>
          <label class="settings-field">
            <span>启动命令</span>
            <input id="mcp-command" type="text" placeholder="npx" />
          </label>
          <label class="settings-field">
            <span>参数（空格分隔）</span>
            <input id="mcp-args" type="text" placeholder="-y @modelcontextprotocol/server-filesystem /Users/you" />
          </label>
        </div>
        <div class="platform-actions">
          <button class="btn-text save-btn" type="button" id="btn-add-mcp">保存并连接</button>
          <button class="btn-text" type="button" id="btn-import-mcp-hermes">从 Hermes 导入</button>
          <button class="btn-text" type="button" id="btn-reload-mcp">重新连接</button>
        </div>

        <h4 class="settings-subtitle">服务器</h4>
        <ul class="mcp-server-list">${serverRows}</ul>
        <h4 class="settings-subtitle">工具列表</h4>
        <div class="mcp-tool-table-wrap">
          <table class="mcp-tool-table">
            <thead><tr><th>工具名</th><th>来源</th><th>说明</th></tr></thead>
            <tbody>${toolRows}</tbody>
          </table>
        </div>
        <div id="mcp-feedback" class="platform-feedback" hidden></div>
      </div>
    `;
    document.getElementById("btn-add-mcp")?.addEventListener("click", addMcpServer);
    document.getElementById("btn-mcp-quickstart-fs")?.addEventListener("click", quickstartFilesystemMcp);
    document.getElementById("btn-import-mcp-hermes")?.addEventListener("click", importMcpFromHermes);
    document.getElementById("btn-reload-mcp")?.addEventListener("click", reloadMcp);
  }

  async function quickstartFilesystemMcp() {
    const feedback = document.getElementById("mcp-feedback");
    const root = document.getElementById("mcp-fs-root")?.value.trim() || "";
    showFeedback(feedback, "info", "正在添加 Filesystem MCP…");
    try {
      mcpStatus = await window.SecretaryAPI.request("POST", "/api/mcp/quickstart/filesystem", { root });
      renderNav();
      renderAgentMcpPane();
      const added = mcpStatus.added ? "已添加" : "已存在，已重新连接";
      showFeedback(
        document.getElementById("mcp-feedback"),
        "success",
        `${added} filesystem · 根目录 ${mcpStatus.root || root || "~/Documents"} · ${mcpStatus.tool_count || 0} 个工具`,
      );
    } catch (error) {
      showFeedback(feedback, "error", `添加失败：${error.message}`);
    }
  }

  async function addMcpServer() {
    const feedback = document.getElementById("mcp-feedback");
    const name = document.getElementById("mcp-name")?.value.trim();
    const command = document.getElementById("mcp-command")?.value.trim();
    const argsRaw = document.getElementById("mcp-args")?.value.trim() || "";
    const args = argsRaw ? argsRaw.split(/\s+/).filter(Boolean) : [];
    if (!name || !command) {
      showFeedback(feedback, "error", "请填写名称和启动命令");
      return;
    }
    showFeedback(feedback, "info", "正在保存并连接…");
    try {
      mcpStatus = await window.SecretaryAPI.request("POST", "/api/mcp/servers", {
        name,
        command,
        args,
        enabled: true,
      });
      renderNav();
      renderAgentMcpPane();
      showFeedback(document.getElementById("mcp-feedback"), "success", `已添加 ${name}，加载 ${mcpStatus.tool_count || 0} 个工具`);
    } catch (error) {
      showFeedback(feedback, "error", `添加失败：${error.message}`);
    }
  }

  async function importMcpFromHermes() {
    const feedback = document.getElementById("mcp-feedback");
    showFeedback(feedback, "info", "正在从 Hermes 导入…");
    try {
      mcpStatus = await window.SecretaryAPI.request("POST", "/api/mcp/import-hermes");
      renderNav();
      renderAgentMcpPane();
      const count = Number(mcpStatus.imported_count || 0);
      showFeedback(
        document.getElementById("mcp-feedback"),
        "success",
        count ? `已从 Hermes 导入 ${count} 个服务器` : "Hermes 里没有新的 MCP 服务器可导入",
      );
    } catch (error) {
      showFeedback(feedback, "error", `导入失败：${error.message}`);
    }
  }

  async function reloadMcp() {
    const feedback = document.getElementById("mcp-feedback");
    showFeedback(feedback, "info", "正在重新连接 MCP…");
    try {
      mcpStatus = await window.SecretaryAPI.request("POST", "/api/mcp/reload");
      renderNav();
      renderAgentMcpPane();
      showFeedback(document.getElementById("mcp-feedback"), "success", `已加载 ${mcpStatus.tool_count || 0} 个 MCP 工具`);
    } catch (error) {
      showFeedback(feedback, "error", `连接失败：${error.message}`);
    }
  }

  async function saveDurableMemory() {
    const memoryEditor = document.getElementById("durable-memory-editor");
    const userEditor = document.getElementById("durable-user-editor");
    const feedback = document.getElementById("durable-memory-feedback");
    if (!memoryEditor || !userEditor || !feedback) return;
    try {
      const updated = await window.SecretaryAPI.request("PUT", "/api/memory/durable", {
        memory_md: memoryEditor.value,
        user_md: userEditor.value,
      });
      durableMemoryMd = updated.memory_md || "";
      durableUserMd = updated.user_md || "";
      memoryEditor.value = durableMemoryMd;
      userEditor.value = durableUserMd;
      showFeedback(feedback, "success", "持久记忆已保存");
    } catch (error) {
      showFeedback(feedback, "error", `保存失败：${error.message}`);
    }
  }

  async function saveProfile() {
    const editor = document.getElementById("profile-editor");
    const feedback = document.getElementById("profile-feedback");
    if (!editor || !feedback) return;
    try {
      const updated = await window.SecretaryAPI.request("PUT", "/api/profile", {
        markdown: editor.value,
      });
      profileMarkdown = updated.markdown;
      profileAutoMarkdown = updated.auto_markdown;
      profileIsUserEdited = updated.is_user_edited;
      showFeedback(feedback, "success", "已保存");
    } catch (error) {
      showFeedback(feedback, "error", `保存失败：${error.message}`);
    }
  }

  async function resetProfile() {
    const feedback = document.getElementById("profile-feedback");
    try {
      const updated = await window.SecretaryAPI.request("DELETE", "/api/profile/user");
      profileMarkdown = updated.markdown;
      profileAutoMarkdown = updated.auto_markdown;
      profileIsUserEdited = updated.is_user_edited;
      const editor = document.getElementById("profile-editor");
      if (editor) {
        editor.value = profileMarkdown;
      }
      showFeedback(feedback, "success", "已恢复自动摘要");
    } catch (error) {
      showFeedback(feedback, "error", `恢复失败：${error.message}`);
    }
  }

  function statusLabel(status) {
    if (status === "ready") return "已连接";
    if (status === "error") return "异常";
    return "未配置";
  }

  function escapeHtml(value) {
    return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replaceAll('"', "&quot;");
  }

  window.SettingsModule = { open: openSettings, reload: loadSettings };
})();
