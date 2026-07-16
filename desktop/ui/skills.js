(function () {
  "use strict";

  const panel = document.getElementById("skills-panel");
  const backdrop = document.getElementById("skills-backdrop");
  const navEl = document.getElementById("skills-nav");
  const contentEl = document.getElementById("skills-content");
  const detailModal = document.getElementById("skill-detail-modal");
  const detailBody = document.getElementById("skill-detail-body");

  let activeSource = "browse";
  let catalog = [];
  let installed = [];
  let sources = [];
  let categories = [];
  let filterKey = "all";
  let categoryFilter = "all";
  let statusFilter = "all";
  let searchQuery = "";
  let detailItem = null;
  let viewMode = "card";
  let densityMode = "compact";
  let installMode = "link";
  const PREFS_KEY = "lumina.skills.manager.prefs.v1";
  const DEFAULT_COL_WIDTHS = {
    name: 160,
    status: 72,
    source: 130,
    category: 90,
    mode: 72,
    desc: 320,
  };
  const TABLE_COLUMNS = [
    { key: "name", label: "名称" },
    { key: "status", label: "状态" },
    { key: "source", label: "来源" },
    { key: "category", label: "分类" },
    { key: "mode", label: "方式" },
    { key: "desc", label: "说明" },
  ];
  let columnWidths = { ...DEFAULT_COL_WIDTHS };
  let columnResizeState = null;

  document.getElementById("btn-skills").addEventListener("click", openSkills);
  document.getElementById("btn-close-skills").addEventListener("click", closeSkills);
  backdrop.addEventListener("click", closeSkills);
  detailModal?.addEventListener("click", (event) => {
    if (event.target === detailModal) {
      closeSkillDetail();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && detailModal && !detailModal.hidden) {
      closeSkillDetail();
    }
  });
  document.addEventListener("mousemove", (event) => {
    if (!columnResizeState) return;
    const delta = event.clientX - columnResizeState.startX;
    const next = Math.max(48, columnResizeState.startWidth + delta);
    columnWidths[columnResizeState.col] = next;
    applyColumnWidth(columnResizeState.col, next);
  });
  document.addEventListener("mouseup", () => {
    if (!columnResizeState) return;
    columnResizeState = null;
    document.body.classList.remove("skill-col-resizing");
    savePrefs();
  });

  async function openSkills() {
    panel.hidden = false;
    backdrop.hidden = false;
    await loadSkills();
  }

  function closeSkills() {
    closeSkillDetail();
    panel.hidden = true;
    backdrop.hidden = true;
  }

  async function loadSkills() {
    contentEl.innerHTML = '<p class="muted">扫描 Agent 技能目录…</p>';
    const [sourceList, installedList, catalogList, categoryPayload] = await Promise.all([
      window.SecretaryAPI.request("GET", "/api/skills/sources"),
      window.SecretaryAPI.request("GET", "/api/skills/installed"),
      window.SecretaryAPI.request("GET", "/api/skills/catalog"),
      window.SecretaryAPI.request("GET", "/api/skills/categories").catch(() => ({ categories: [] })),
    ]);
    sources = sourceList;
    installed = installedList;
    catalog = catalogList;
    categories = categoryPayload.categories || [];
    loadPrefs();
    renderNav();
    renderContent();
  }

  function renderNav() {
    navEl.innerHTML = "";
    for (const tab of [
      { key: "browse", label: "浏览" },
      { key: "installed", label: "已安装" },
    ]) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `skills-tab${activeSource === tab.key ? " active" : ""}`;
      btn.textContent = tab.label;
      btn.addEventListener("click", () => {
        activeSource = tab.key;
        renderNav();
        renderContent();
      });
      navEl.appendChild(btn);
    }
  }

  function filteredItems(items) {
    let result = items;
    if (filterKey !== "all") {
      result = result.filter((item) => item.source_key === filterKey);
    }
    if (categoryFilter !== "all") {
      result = result.filter((item) => item.category === categoryFilter);
    }
    if (statusFilter !== "all") {
      result = result.filter((item) => item.status === statusFilter);
    }
    const query = searchQuery.trim().toLowerCase();
    if (!query) {
      return result;
    }
    return result.filter(
      (item) =>
        item.name.toLowerCase().includes(query) ||
        item.description.toLowerCase().includes(query) ||
        item.path.toLowerCase().includes(query) ||
        String(item.origin_path || "").toLowerCase().includes(query),
    );
  }

  function renderContent() {
    if (activeSource === "installed") {
      renderInstalledPane(filteredItems(installed));
      return;
    }
    renderBrowsePane(filteredItems(catalog));
  }

  function renderBrowsePane(items) {
    const pending = items.filter((item) => !item.installed).length;
    contentEl.innerHTML = `
      <div class="skills-pane">
        ${renderToolbar({ items, pending, showFilters: true })}
        <div class="skills-view ${densityMode}">${renderSkillCollection(items)}</div>
        <div id="skill-feedback" class="platform-feedback" hidden></div>
      </div>
    `;
    bindToolbarEvents();
    bindSkillListEvents(items);
    bindColumnResize();
  }

  function renderInstalledPane(items) {
    contentEl.innerHTML = `
      <div class="skills-pane">
        ${renderToolbar({ items, pending: 0, showFilters: false })}
        <div class="skills-view ${densityMode}">${renderSkillCollection(items)}</div>
        <div id="skill-feedback" class="platform-feedback" hidden></div>
      </div>
    `;
    bindToolbarEvents();
    bindSkillListEvents(items);
    bindColumnResize();
  }

  function renderToolbar({ items, pending, showFilters }) {
    const filterOptions = sources
      .map(
        (source) =>
          `<option value="${escapeAttr(source.key)}"${source.key === filterKey ? " selected" : ""}>${escapeHtml(source.label)} (${source.count || 0})</option>`,
      )
      .join("");
    const categoryOptions = ['<option value="all">全部分类</option>']
      .concat((categories.length ? categories : fallbackCategories()).map((cat) =>
        `<option value="${escapeAttr(cat)}"${cat === categoryFilter ? " selected" : ""}>${escapeHtml(cat)}</option>`,
      ))
      .join("");
    const statusOptions = [
      { key: "all", label: "全部状态" },
      { key: "available", label: "可挂靠" },
      { key: "ok", label: "正常" },
      { key: "conflict", label: "冲突" },
      { key: "broken_link", label: "断链" },
      { key: "missing_skill_md", label: "缺 SKILL.md" },
    ]
      .map(
        (item) =>
          `<option value="${item.key}"${item.key === statusFilter ? " selected" : ""}>${item.label}</option>`,
      )
      .join("");
    const totalCount = activeSource === "installed" ? installed.length : catalog.length;
    const meta =
      activeSource === "installed"
        ? `共 ${totalCount} · 筛选 ${items.length}`
        : `共 ${totalCount} · 筛选 ${items.length} · 待挂靠 ${pending}`;
    return `
      <div class="skill-toolbar">
        <span class="skill-meta-line">${meta} · 双击查看详情</span>
        ${
          showFilters
            ? `<button type="button" class="btn primary skill-copy-all" id="btn-copy-all"${pending ? "" : " disabled"}>一键挂靠${pending ? ` (${pending})` : ""}</button>`
            : ""
        }
        <input id="skill-search" type="search" placeholder="搜索…" value="${escapeAttr(searchQuery)}" />
        ${
          showFilters
            ? `<select id="skill-filter">${filterOptions}</select>
               <select id="skill-category-filter">${categoryOptions}</select>
               <select id="skill-status-filter">${statusOptions}</select>
               <select id="skill-install-mode">
                 <option value="link"${installMode === "link" ? " selected" : ""}>软挂靠</option>
                 <option value="copy"${installMode === "copy" ? " selected" : ""}>复制</option>
               </select>`
            : ""
        }
        <div class="skill-toolbar-switch">
          <button type="button" class="btn-text${viewMode === "list" ? " active" : ""}" id="btn-view-list">列表</button>
          <button type="button" class="btn-text${viewMode === "card" ? " active" : ""}" id="btn-view-card">方框</button>
        </div>
        <div class="skill-toolbar-switch">
          <button type="button" class="btn-text${densityMode === "compact" ? " active" : ""}" id="btn-density-compact">紧凑</button>
          <button type="button" class="btn-text${densityMode === "comfortable" ? " active" : ""}" id="btn-density-comfortable">舒适</button>
        </div>
      </div>
    `;
  }

  function bindToolbarEvents() {
    document.getElementById("btn-copy-all")?.addEventListener("click", copyAllSkills);
    document.getElementById("btn-skills-empty-action")?.addEventListener("click", () => {
      void loadSkills();
    });
    document.getElementById("skill-search")?.addEventListener("input", (event) => {
      searchQuery = event.target.value;
      renderContent();
    });
    document.getElementById("skill-filter")?.addEventListener("change", (event) => {
      filterKey = event.target.value;
      renderContent();
    });
    document.getElementById("skill-category-filter")?.addEventListener("change", (event) => {
      categoryFilter = event.target.value;
      renderContent();
    });
    document.getElementById("skill-status-filter")?.addEventListener("change", (event) => {
      statusFilter = event.target.value;
      renderContent();
    });
    document.getElementById("skill-install-mode")?.addEventListener("change", (event) => {
      installMode = event.target.value;
      savePrefs();
    });
    document.getElementById("btn-view-list")?.addEventListener("click", () => {
      viewMode = "list";
      savePrefs();
      renderContent();
    });
    document.getElementById("btn-view-card")?.addEventListener("click", () => {
      viewMode = "card";
      savePrefs();
      renderContent();
    });
    document.getElementById("btn-density-compact")?.addEventListener("click", () => {
      densityMode = "compact";
      savePrefs();
      renderContent();
    });
    document.getElementById("btn-density-comfortable")?.addEventListener("click", () => {
      densityMode = "comfortable";
      savePrefs();
      renderContent();
    });
  }

  async function copyAllSkills() {
    const button = document.getElementById("btn-copy-all");
    const feedback = document.getElementById("skill-feedback");
    if (!button || !feedback) return;
    button.disabled = true;
    button.textContent = "挂靠中…";
    showFeedback(feedback, "info", "正在批量挂靠，请稍候…");
    try {
      const params = new URLSearchParams();
      if (filterKey && filterKey !== "all") {
        params.set("source", filterKey);
      }
      params.set("install_mode", installMode);
      const query = params.toString() ? `?${params.toString()}` : "";
      const result = await window.SecretaryAPI.request("POST", `/api/skills/install-all${query}`);
      showFeedback(feedback, result.failed?.length ? "error" : "success", result.message);
      await loadSkills();
      activeSource = "installed";
      renderNav();
      renderContent();
    } catch (error) {
      showFeedback(feedback, "error", error.message);
      button.disabled = false;
      renderContent();
    }
  }

  function renderSkillCollection(items) {
    if (!items.length) {
      const voice = activeSource === "installed"
        ? "还没有挂靠的技能。把常用工作流放进来，灵犀就能按需调用。"
        : "这里暂时没有匹配的技能。换个筛选，或重新扫描技能目录。";
      return `
        <div class="skills-empty">
          <p>${escapeHtml(voice)}</p>
          <button class="btn-text" type="button" id="btn-skills-empty-action">重新扫描</button>
        </div>
      `;
    }
    if (viewMode === "card") {
      return `
        <div class="skill-card-grid">
          ${items.map((item) => renderSkillCard(item)).join("")}
        </div>
      `;
    }
    return `
      <div class="skill-table-wrap">
        <table class="skill-table">
          <thead>
            <tr>
              ${TABLE_COLUMNS.map((col) => renderTableHead(col)).join("")}
            </tr>
          </thead>
          <tbody>
            ${items.map((item) => renderSkillRow(item)).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderTableHead(col) {
    const width = columnWidths[col.key] || DEFAULT_COL_WIDTHS[col.key];
    return `
      <th class="col-${col.key}" data-col="${col.key}" style="width:${width}px">
        ${col.label}
        <span class="col-resizer" data-col="${col.key}"></span>
      </th>
    `;
  }

  function applyColumnWidth(col, width) {
    const th = contentEl.querySelector(`th[data-col="${col}"]`);
    if (th) {
      th.style.width = `${width}px`;
    }
  }

  function bindColumnResize() {
    contentEl.querySelectorAll(".col-resizer").forEach((handle) => {
      handle.addEventListener("mousedown", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const col = handle.dataset.col || "";
        const th = handle.closest("th");
        if (!col || !th) return;
        columnResizeState = {
          col,
          startX: event.clientX,
          startWidth: th.offsetWidth,
        };
        document.body.classList.add("skill-col-resizing");
      });
    });
  }

  function renderSkillCard(item) {
    const tip = [item.description, item.origin_path || item.path].filter(Boolean).join("\n");
    return `
      <button
        type="button"
        class="skill-chip status-${escapeAttr(item.status || "unknown")}"
        data-skill-id="${escapeAttr(buildSkillId(item))}"
        title="${escapeAttr(tip)}"
      >
        <span class="skill-chip-name">${escapeHtml(item.name)}</span>
        <span class="skill-chip-meta">${escapeHtml(statusLabel(item.status))} · ${escapeHtml(item.category || "其他")}</span>
      </button>
    `;
  }

  function renderSkillRow(item) {
    const tip = item.origin_path || item.path || "";
    return `
      <tr data-skill-id="${escapeAttr(buildSkillId(item))}" title="${escapeAttr(tip)}">
        <td class="col-name">${escapeHtml(item.name)}</td>
        <td class="col-status">${escapeHtml(statusLabel(item.status))}</td>
        <td class="col-source">${escapeHtml(item.source_label)}</td>
        <td class="col-category">${escapeHtml(item.category || "其他")}</td>
        <td class="col-mode">${escapeHtml(item.install_mode || "—")}</td>
        <td class="col-desc">${escapeHtml(item.description || "—")}</td>
      </tr>
    `;
  }

  function openSkillDetail(item) {
    if (!detailModal || !detailBody) return;
    detailItem = item;
    detailBody.innerHTML = renderSkillDetail(item);
    detailModal.hidden = false;
    bindDetailEvents(item);
  }

  function closeSkillDetail() {
    if (!detailModal) return;
    detailModal.hidden = true;
    detailBody.innerHTML = "";
    detailItem = null;
  }

  function renderSkillDetail(item) {
    const tagsText = Array.isArray(item.tags) ? item.tags.join(", ") : "";
    const categoryOptions = (categories.length ? categories : fallbackCategories())
      .map((cat) => `<option value="${escapeAttr(cat)}"${cat === item.category ? " selected" : ""}>${escapeHtml(cat)}</option>`)
      .join("");
    const canInstall = !item.installed;
    return `
      <div class="skill-detail-panel">
        <div class="skill-detail-dialog-head">
          <h4 id="skill-detail-title">${escapeHtml(item.name)}</h4>
          <button type="button" class="skill-detail-close" id="btn-close-skill-detail" aria-label="关闭">×</button>
        </div>
        <p class="skill-row-desc">${escapeHtml(item.description || "无描述")}</p>
        <div class="skill-detail-meta">
          <div><span>来源</span><code>${escapeHtml(item.source_label)}</code></div>
          <div><span>源路径</span><code>${escapeHtml(item.origin_path || item.path)}</code></div>
          <div><span>挂靠目录</span><code>${escapeHtml(item.path || "—")}</code></div>
          <div><span>安装</span><code>${escapeHtml(item.install_mode || "none")}</code></div>
          <div><span>状态</span><code>${escapeHtml(statusLabel(item.status))}</code></div>
        </div>
        <label class="settings-field">
          <span>分类</span>
          <select id="skill-category-input">${categoryOptions}</select>
        </label>
        <label class="settings-field">
          <span>标签</span>
          <input id="skill-tags-input" type="text" value="${escapeAttr(tagsText)}" placeholder="逗号分隔" />
        </label>
        <div class="platform-actions">
          <button class="btn-text save-btn" type="button" id="btn-save-skill-category">保存分类</button>
          ${
            canInstall
              ? '<button class="btn-text" type="button" id="btn-install-skill">挂靠</button>'
              : '<button class="btn-text" type="button" id="btn-uninstall-skill">卸载</button>'
          }
          ${item.installed ? '<button class="btn-text" type="button" id="btn-view-skill-body">SKILL.md</button>' : ""}
        </div>
        <pre id="skill-body-preview" class="skill-body-preview" hidden></pre>
      </div>
    `;
  }

  function bindDetailEvents(item) {
    document.getElementById("btn-close-skill-detail")?.addEventListener("click", closeSkillDetail);
    document.getElementById("btn-save-skill-category")?.addEventListener("click", () => saveSkillCategory(item.name));
    document.getElementById("btn-install-skill")?.addEventListener("click", () => installSingleSkill(item));
    document.getElementById("btn-uninstall-skill")?.addEventListener("click", () => uninstallSingleSkill(item.name));
    document.getElementById("btn-view-skill-body")?.addEventListener("click", () => viewSkillBody(item.name));
  }

  function bindSkillListEvents(items) {
    contentEl.querySelectorAll("[data-skill-id]").forEach((node) => {
      node.addEventListener("dblclick", () => {
        const id = node.dataset.skillId || "";
        const item = items.find((entry) => buildSkillId(entry) === id);
        if (item) {
          openSkillDetail(item);
        }
      });
    });
  }

  async function installSingleSkill(item) {
    try {
      await window.SecretaryAPI.request("POST", "/api/skills/install", {
        source_path: item.origin_path || item.path,
        install_mode: installMode,
      });
      await loadSkills();
      showFeedback(document.getElementById("skill-feedback"), "success", "已完成挂靠");
      closeSkillDetail();
      activeSource = "installed";
      renderNav();
      renderContent();
    } catch (error) {
      showFeedback(document.getElementById("skill-feedback"), "error", `挂靠失败：${error.message}`);
    }
  }

  async function uninstallSingleSkill(name) {
    try {
      await window.SecretaryAPI.request("POST", "/api/skills/uninstall", { name });
      await loadSkills();
      closeSkillDetail();
      showFeedback(document.getElementById("skill-feedback"), "success", "已卸载");
    } catch (error) {
      showFeedback(document.getElementById("skill-feedback"), "error", `卸载失败：${error.message}`);
    }
  }

  async function saveSkillCategory(name) {
    const category = document.getElementById("skill-category-input")?.value || "其他";
    const tagsRaw = document.getElementById("skill-tags-input")?.value || "";
    const tags = tagsRaw
      .split(",")
      .map((tag) => tag.trim())
      .filter(Boolean);
    try {
      await window.SecretaryAPI.request("PUT", `/api/skills/${encodeURIComponent(name)}/category`, {
        category,
        tags,
      });
      await loadSkills();
      if (detailItem && detailItem.name === name) {
        const refreshed = [...catalog, ...installed].find((entry) => entry.name === name);
        if (refreshed) {
          openSkillDetail(refreshed);
        }
      }
      showFeedback(document.getElementById("skill-feedback"), "success", "分类已保存");
    } catch (error) {
      showFeedback(document.getElementById("skill-feedback"), "error", `保存分类失败：${error.message}`);
    }
  }

  async function viewSkillBody(name) {
    try {
      const payload = await window.SecretaryAPI.request("GET", `/api/skills/installed/${encodeURIComponent(name)}`);
      const block = document.getElementById("skill-body-preview");
      if (!block) return;
      block.hidden = false;
      block.textContent = payload.markdown || "";
    } catch (error) {
      showFeedback(document.getElementById("skill-feedback"), "error", `读取失败：${error.message}`);
    }
  }

  function buildSkillId(item) {
    return `${item.name}::${item.path}`;
  }

  function statusLabel(status) {
    if (status === "ok") return "正常";
    if (status === "available") return "可挂靠";
    if (status === "broken_link") return "断链";
    if (status === "missing_skill_md") return "缺SKILL";
    if (status === "conflict") return "冲突";
    return status || "未知";
  }

  function fallbackCategories() {
    return ["开发", "设计", "内容", "办公协同", "自动化", "数据分析", "系统工具", "其他"];
  }

  function loadPrefs() {
    try {
      const raw = localStorage.getItem(PREFS_KEY);
      if (!raw) return;
      const prefs = JSON.parse(raw);
      if (prefs.viewMode === "list" || prefs.viewMode === "card") viewMode = prefs.viewMode;
      if (prefs.densityMode === "compact" || prefs.densityMode === "comfortable") densityMode = prefs.densityMode;
      if (prefs.installMode === "link" || prefs.installMode === "copy") installMode = prefs.installMode;
      if (prefs.columnWidths && typeof prefs.columnWidths === "object") {
        columnWidths = { ...DEFAULT_COL_WIDTHS, ...prefs.columnWidths };
      }
    } catch (_error) {
      // ignore
    }
  }

  function savePrefs() {
    localStorage.setItem(
      PREFS_KEY,
      JSON.stringify({ viewMode, densityMode, installMode, columnWidths }),
    );
  }

  function showFeedback(element, kind, text) {
    if (!element) return;
    element.hidden = false;
    element.className = `platform-feedback ${kind}`;
    element.textContent = text;
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replaceAll('"', "&quot;");
  }

  window.SkillsModule = { open: openSkills, close: closeSkills };
})();
