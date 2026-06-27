(function () {
  "use strict";

  const statusBadge = document.getElementById("kb-status-badge");
  const emptyPanel = document.getElementById("kb-empty");
  const emptyMessage = document.getElementById("kb-empty-message");
  const layout = document.getElementById("kb-layout");
  const statsEl = document.getElementById("kb-stats");
  const tagsEl = document.getElementById("kb-tags");
  const sourcesEl = document.getElementById("kb-sources");
  const loadMoreBtn = document.getElementById("btn-load-more");
  const searchForm = document.getElementById("kb-search-form");
  const searchInput = document.getElementById("kb-search-input");
  const searchResults = document.getElementById("kb-search-results");
  const previewTitle = document.getElementById("kb-preview-title");
  const previewPath = document.getElementById("kb-preview-path");
  const previewBody = document.getElementById("kb-preview-body");

  let config = null;
  let sourceOffset = 0;
  const SOURCE_PAGE = 50;
  let hasMoreSources = false;

  document.getElementById("btn-import").addEventListener("click", importNow);
  loadMoreBtn.addEventListener("click", () => loadSources(false));
  searchForm.addEventListener("submit", onSearch);
  sourcesEl.addEventListener("click", (event) => {
    const button = event.target.closest("[data-source-path]");
    if (!button) return;
    openSource(button.dataset.sourcePath);
  });
  searchResults.addEventListener("click", (event) => {
    const button = event.target.closest("[data-source-path]");
    if (!button) return;
    openSource(button.dataset.sourcePath);
  });

  boot();

  async function boot() {
    try {
      config = await window.SecretaryAPI.request("GET", "/api/shibei/config");
    } catch (error) {
      showEmpty(`无法加载 Shibei 配置：${error.message}`);
      return;
    }
    renderStatus(config);
    if (!config.enabled) {
      showEmpty("Shibei 知识库已关闭。请在主窗口「设置 → Shibei 知识库」中启用。");
      return;
    }
    if (!config.shibei_available) {
      showEmpty(config.status_message || "未检测到 Shibei 安装，请填写 install_path。");
      return;
    }
    if (!config.sources?.length) {
      showEmpty("请添加需要监控的文件夹。");
      return;
    }
    layout.hidden = false;
    emptyPanel.hidden = true;
    sourceOffset = 0;
    sourcesEl.innerHTML = "";
    await loadSources(true);
  }

  function showEmpty(message) {
    emptyMessage.textContent = message;
    emptyPanel.hidden = false;
    layout.hidden = true;
  }

  function renderStatus(cfg) {
    const label = cfg.status_message || cfg.status || "未知";
    statusBadge.textContent = label;
    statusBadge.dataset.status = cfg.status || "unknown";
  }

  async function loadSources(reset) {
    if (reset) {
      sourceOffset = 0;
      sourcesEl.innerHTML = "";
    }
    loadMoreBtn.disabled = true;
    try {
      const payload = await window.SecretaryAPI.request(
        "GET",
        `/api/shibei/sources?limit=${SOURCE_PAGE}&offset=${sourceOffset}`,
      );
      renderStats(payload);
      renderSourceList(payload.sources || [], reset);
      hasMoreSources = Boolean(payload.has_more);
      sourceOffset += (payload.sources || []).length;
      loadMoreBtn.hidden = !hasMoreSources;
    } catch (error) {
      if (reset) {
        showEmpty(`读取 Shibei 索引失败：${error.message}`);
      } else {
        previewBody.textContent = `加载更多失败：${error.message}`;
      }
    } finally {
      loadMoreBtn.disabled = false;
    }
  }

  function renderStats(payload) {
    const summary = payload.summary || {};
    const totalFiles = summary.total_files ?? payload.count ?? 0;
    const totalChunks = summary.total_chunks ?? 0;
    const engines = (summary.engines || [config?.search_engine || "bm25"]).join(", ");
    statsEl.innerHTML = `
      <div><dt>文档</dt><dd>${totalFiles}</dd></div>
      <div><dt>片段</dt><dd>${totalChunks}</dd></div>
      <div><dt>引擎</dt><dd>${escapeHtml(engines)}</dd></div>
      <div><dt>集合</dt><dd>${escapeHtml(config?.collection || "lumina_kb")}</dd></div>
    `;
    const byTag = summary.by_tag || {};
    const tagEntries = Object.entries(byTag).slice(0, 12);
    if (!tagEntries.length) {
      tagsEl.innerHTML = "";
      return;
    }
    tagsEl.innerHTML = tagEntries
      .map(
        ([tag, count]) =>
          `<button type="button" class="kb-tag" data-tag="${escapeAttr(tag)}">${escapeHtml(tag)} (${count})</button>`,
      )
      .join("");
    tagsEl.querySelectorAll(".kb-tag").forEach((chip) => {
      chip.addEventListener("click", () => {
        searchInput.value = chip.dataset.tag || "";
        searchForm.requestSubmit();
      });
    });
  }

  function renderSourceList(items, reset) {
    if (reset && !items.length) {
      sourcesEl.innerHTML = `<p class="kb-muted">索引为空。点击「导入」扫描监控文件夹。</p>`;
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const item of items) {
      const path = typeof item === "string" ? item : item.source || item.path || item.file || "";
      if (!path) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "kb-source-item";
      button.dataset.sourcePath = path;
      button.innerHTML = `<span class="kb-source-name">${escapeHtml(basename(path))}</span><span class="kb-source-dir">${escapeHtml(dirname(path))}</span>`;
      fragment.appendChild(button);
    }
    sourcesEl.appendChild(fragment);
  }

  async function openSource(path) {
    previewTitle.textContent = basename(path);
    previewPath.textContent = path;
    previewBody.textContent = "加载中…";
    searchResults.hidden = true;
    try {
      const data = await window.SecretaryAPI.request(
        "GET",
        `/api/shibei/source?path=${encodeURIComponent(path)}`,
      );
      previewBody.textContent = data.content || "";
    } catch (error) {
      previewBody.textContent = `无法读取文件：${error.message}`;
    }
  }

  async function onSearch(event) {
    event.preventDefault();
    const query = searchInput.value.trim();
    if (!query) return;
    searchResults.hidden = false;
    searchResults.innerHTML = `<p class="kb-muted">搜索「${escapeHtml(query)}」…</p>`;
    try {
      const payload = await window.SecretaryAPI.request("POST", "/api/shibei/search", {
        query,
        limit: 12,
      });
      renderSearchResults(payload);
    } catch (error) {
      searchResults.innerHTML = `<p class="kb-muted">搜索失败：${escapeHtml(error.message)}</p>`;
    }
  }

  function renderSearchResults(payload) {
    const results = payload.results || [];
    if (!results.length) {
      searchResults.innerHTML = `<p class="kb-muted">未找到与「${escapeHtml(payload.query || "")}」相关的内容。</p>`;
      return;
    }
    searchResults.innerHTML = results
      .map((item) => {
        const source = item.source || "";
        const score = item.score ?? "";
        const tags = item.tags ? ` · ${escapeHtml(String(item.tags))}` : "";
        const text = escapeHtml(String(item.text || "").trim());
        return `
          <button type="button" class="kb-hit" data-source-path="${escapeAttr(source)}">
            <div class="kb-hit-head">
              <strong>${escapeHtml(basename(source))}</strong>
              <span class="kb-hit-meta">score ${score}${tags}</span>
            </div>
            <p class="kb-hit-text">${text}</p>
          </button>`;
      })
      .join("");
  }

  async function importNow() {
    const button = document.getElementById("btn-import");
    button.disabled = true;
    button.textContent = "导入中…";
    try {
      const result = await window.SecretaryAPI.request("POST", "/api/shibei/import");
      statusBadge.textContent = result.message;
      config = await window.SecretaryAPI.request("GET", "/api/shibei/config");
      renderStatus(config);
      await loadSources(true);
    } catch (error) {
      statusBadge.textContent = `导入失败：${error.message}`;
    } finally {
      button.disabled = false;
      button.textContent = "导入";
    }
  }

  function basename(path) {
    const parts = String(path).split(/[/\\]/);
    return parts[parts.length - 1] || path;
  }

  function dirname(path) {
    const parts = String(path).split(/[/\\]/);
    parts.pop();
    const parent = parts.join("/");
    if (parent.length > 72) {
      return "…" + parent.slice(-69);
    }
    return parent || "/";
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replaceAll("'", "&#39;");
  }
})();
