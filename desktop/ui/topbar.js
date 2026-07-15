(function () {
  "use strict";

  const TOKEN_STATE_KEY = "lumina.token.usage.v1";
  const APPROX_TOKEN_RATIO = 1.8;
  const UI_PREFS_KEY = "lumina.ui.preferences.v1";

  const menuBtn = document.getElementById("btn-topbar-menu");
  const menuPanel = document.getElementById("topbar-menu");
  const tokenValueEl = document.getElementById("token-usage-value");
  const modelEl = document.getElementById("topbar-model");
  const aboutBtn = document.getElementById("btn-about");
  const aboutPanel = document.getElementById("about-panel");
  const aboutBackdrop = document.getElementById("about-backdrop");
  const closeAboutBtn = document.getElementById("btn-close-about");

  // Apply chrome prefs (theme included) even if menu nodes are missing.
  applyUiPreferences(loadUiPreferences());
  window.addEventListener("lumina:ui-preferences", (event) => {
    applyUiPreferences(event.detail || loadUiPreferences());
  });

  // Moon button must init even if other chrome nodes are missing.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initMoonButton);
  } else {
    initMoonButton();
  }

  if (!menuBtn || !menuPanel || !tokenValueEl || !modelEl) {
    return;
  }

  let totalTokens = loadTokenState();
  renderTokenUsage();
  loadActiveModel();

  menuBtn.addEventListener("click", () => {
    const expanded = menuBtn.getAttribute("aria-expanded") === "true";
    setMenuOpen(!expanded);
  });

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (menuPanel.contains(target) || menuBtn.contains(target)) return;
    setMenuOpen(false);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (aboutPanel && !aboutPanel.hidden) {
        closeAbout();
        return;
      }
      const moonBar = document.getElementById("moon-info-bar");
      if (moonBar && !moonBar.hidden) {
        toggleMoonInfoBar();
        return;
      }
      setMenuOpen(false);
    }
  });

  menuPanel.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest("button")) {
      setMenuOpen(false);
    }
  });

  aboutBtn?.addEventListener("click", openAbout);
  closeAboutBtn?.addEventListener("click", closeAbout);
  aboutBackdrop?.addEventListener("click", closeAbout);

  window.addEventListener("lumina:api-response", (event) => {
    const detail = event.detail || {};
    const route = String(detail.route || "");
    if (route === "/api/agent/config" || route.startsWith("/api/agent/config/")) {
      const body = detail.responseBody || {};
      if (body.model) {
        renderActiveModel(body.model, body.status);
      }
    }
    if (route !== "/api/chat" && route !== "/api/chat/confirm") {
      return;
    }
    const responseBody = detail.responseBody || {};
    let delta = Number(responseBody.usage_total_tokens || 0);
    if (!Number.isFinite(delta) || delta <= 0) {
      const requestBody = detail.requestBody || {};
      let inputText = "";
      if (typeof requestBody.message === "string") {
        inputText = requestBody.message;
      }
      let outputText = "";
      if (typeof responseBody.reply === "string") {
        outputText = responseBody.reply;
      }
      if (typeof responseBody.profile_excerpt === "string") {
        outputText += responseBody.profile_excerpt;
      }
      delta = estimateTokens(inputText + outputText);
    }
    if (delta <= 0) return;
    totalTokens += delta;
    saveTokenState(totalTokens);
    renderTokenUsage();
  });

  window.addEventListener("lumina:language", () => {
    window.LuminaI18n?.applyDocument();
    loadActiveModel();
  });

  window.addEventListener("lumina:agent-config", (event) => {
    const detail = event.detail || {};
    if (detail.model) {
      renderActiveModel(detail.model, detail.status);
    } else {
      loadActiveModel();
    }
  });

  async function loadActiveModel() {
    if (!window.SecretaryAPI) {
      renderActiveModel("", "error");
      return;
    }
    try {
      const config = await window.SecretaryAPI.request("GET", "/api/agent/config");
      renderActiveModel(config.model, config.status);
    } catch (_error) {
      renderActiveModel("", "error");
    }
  }

  function renderActiveModel(model, status) {
    const t = (key) => window.LuminaI18n?.t(key) || key;
    const name = String(model || "").trim();
    if (!name) {
      modelEl.textContent = status === "ready" ? t("model.unset") : t("model.unconfigured");
      modelEl.title = t("model.current");
      return;
    }
    modelEl.textContent = shortenModelName(name);
    modelEl.title = name;
  }

  function shortenModelName(name) {
    if (name.length <= 28) return name;
    return `${name.slice(0, 26)}…`;
  }

  function openAbout() {
    if (!aboutPanel || !aboutBackdrop) return;
    aboutPanel.hidden = false;
    aboutBackdrop.hidden = false;
  }

  function closeAbout() {
    if (!aboutPanel || !aboutBackdrop) return;
    aboutPanel.hidden = true;
    aboutBackdrop.hidden = true;
  }

  function setMenuOpen(open) {
    menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    menuPanel.hidden = !open;
  }

  function estimateTokens(text) {
    const cleaned = String(text || "").trim();
    if (!cleaned) return 0;
    return Math.max(1, Math.round(cleaned.length / APPROX_TOKEN_RATIO));
  }

  function renderTokenUsage() {
    tokenValueEl.textContent = formatNumber(totalTokens);
  }

  function loadTokenState() {
    try {
      const raw = localStorage.getItem(TOKEN_STATE_KEY);
      if (!raw) return 0;
      const value = Number(raw);
      if (!Number.isFinite(value) || value < 0) return 0;
      return Math.floor(value);
    } catch (_error) {
      return 0;
    }
  }

  function saveTokenState(value) {
    localStorage.setItem(TOKEN_STATE_KEY, String(Math.max(0, Math.floor(value))));
  }

  function formatNumber(value) {
    if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
    if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
    return String(value);
  }

  function loadUiPreferences() {
    try {
      const raw = localStorage.getItem(UI_PREFS_KEY);
      if (!raw) return { density: "comfortable", messageWidth: "medium", language: "bi", theme: "system" };
      const parsed = JSON.parse(raw);
      const language = ["zh", "en", "bi"].includes(parsed?.language) ? parsed.language : "bi";
      const theme = ["system", "light", "dark", "paper"].includes(parsed?.theme) ? parsed.theme : "system";
      return {
        density: parsed?.density === "compact" ? "compact" : "comfortable",
        messageWidth: ["narrow", "medium", "wide"].includes(parsed?.messageWidth)
          ? parsed.messageWidth
          : "medium",
        language,
        theme,
      };
    } catch (_error) {
      return { density: "comfortable", messageWidth: "medium", language: "bi", theme: "system" };
    }
  }

  function applyUiPreferences(prefs) {
    const density = prefs?.density === "compact" ? "compact" : "comfortable";
    const width = ["narrow", "medium", "wide"].includes(prefs?.messageWidth)
      ? prefs.messageWidth
      : "medium";
    const theme = ["system", "light", "dark", "paper"].includes(prefs?.theme) ? prefs.theme : "system";
    document.body.classList.toggle("ui-density-compact", density === "compact");
    document.body.classList.toggle("ui-width-narrow", width === "narrow");
    document.body.classList.toggle("ui-width-medium", width === "medium");
    document.body.classList.toggle("ui-width-wide", width === "wide");
    if (window.LuminaTheme) {
      window.LuminaTheme.apply(theme);
    } else if (theme === "light" || theme === "dark" || theme === "paper") {
      document.documentElement.setAttribute("data-theme", theme);
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
  }

  /* ===== 月相按钮 + 顶部信息条 ===== */
  function renderMoonButton() {
    const btn = document.getElementById("btn-moon");
    if (!btn || !window.LuminaLunar) return;
    const now = new Date();
    btn.innerHTML = window.LuminaLunar.moonSVG(now, 24);
  }

  function renderMoonInfoBar() {
    const bar = document.getElementById("moon-info-bar");
    if (!bar || !window.LuminaLunar) return;
    const now = new Date();
    const name = window.LuminaLunar.moonPhaseName(now);
    const lunarDay = window.LuminaLunar.lunarDayLabel(now);
    const term = window.LuminaLunar.getSolarTerm(now);
    const dateStr = `${now.getFullYear()}.${String(now.getMonth() + 1).padStart(2, "0")}.${String(now.getDate()).padStart(2, "0")}`;
    const weekDays = ["日", "一", "二", "三", "四", "五", "六"];
    const week = `周${weekDays[now.getDay()]}`;
    const parts = [dateStr, week, lunarDay, name];
    if (term) parts.push(term);
    bar.textContent = parts.join(" · ");
  }

  let moonInfoBarTimer = null;

  function toggleMoonInfoBar() {
    const btn = document.getElementById("btn-moon");
    const bar = document.getElementById("moon-info-bar");
    if (!btn || !bar) return;
    if (!bar.hidden) {
      bar.hidden = true;
      btn.setAttribute("aria-expanded", "false");
      if (moonInfoBarTimer) {
        clearInterval(moonInfoBarTimer);
        moonInfoBarTimer = null;
      }
    } else {
      renderMoonInfoBar();
      bar.hidden = false;
      btn.setAttribute("aria-expanded", "true");
      if (moonInfoBarTimer) clearInterval(moonInfoBarTimer);
      moonInfoBarTimer = setInterval(renderMoonInfoBar, 60_000);
    }
  }

  function initMoonButton() {
    renderMoonButton();
    const btn = document.getElementById("btn-moon");
    if (btn) btn.addEventListener("click", toggleMoonInfoBar);
  }
})();
