(function () {
  "use strict";

  const WRITE_TOOLS = /^(write|file_write|edit|patch|file_edit|edit_file|str_replace|apply_patch|move)$/;
  const PREVIEW_EXTS = new Set([
    ".md",
    ".markdown",
    ".txt",
    ".json",
    ".csv",
    ".tsv",
    ".xlsx",
    ".xlsm",
    ".pdf",
    ".docx",
    ".html",
    ".htm",
    ".yaml",
    ".yml",
    ".py",
    ".js",
    ".ts",
    ".log",
  ]);

  const panel = document.getElementById("artifact-panel");
  const treeEl = document.getElementById("artifact-tree");
  const previewEl = document.getElementById("artifact-preview");
  const titleEl = document.getElementById("artifact-title");
  const metaEl = document.getElementById("artifact-meta");
  const emptyEl = document.getElementById("artifact-empty");
  const rootSelect = document.getElementById("artifact-root-select");
  const btnClose = document.getElementById("btn-artifact-close");
  const btnOpenExternal = document.getElementById("btn-artifact-open-external");
  const btnRefresh = document.getElementById("btn-artifact-refresh");
  const btnModeDocs = document.getElementById("btn-artifact-mode-docs");
  const btnModeContext = document.getElementById("btn-artifact-mode-context");
  const docsView = document.getElementById("artifact-docs-view");
  const contextView = document.getElementById("artifact-context-view");
  const contextEmptyEl = document.getElementById("artifact-context-empty");
  const contextContentEl = document.getElementById("artifact-context-content");
  const workspace = document.querySelector(".workspace");

  /** @type {{ path: string, name: string, source: string }[]} */
  let sessionFiles = [];
  /** @type {Map<string, object>} */
  const contextByThread = new Map();
  let threadId = "";
  let workspacePath = "";
  let sandboxPath = "";
  let activeRoot = "";
  let activeFile = "";
  let open = false;
  let panelMode = localStorage.getItem("artifactPanelMode") === "context" ? "context" : "documents";

  function basename(path) {
    const text = String(path || "").replace(/[/\\]+$/, "");
    const parts = text.split(/[/\\]/);
    return parts[parts.length - 1] || text;
  }

  function extOf(path) {
    const name = basename(path);
    const idx = name.lastIndexOf(".");
    return idx >= 0 ? name.slice(idx).toLowerCase() : "";
  }

  function isPreviewable(path) {
    return PREVIEW_EXTS.has(extOf(path)) || !extOf(path);
  }

    function escapeHtml(value) {
    return window.LuminaUtils?.escapeHtml
      ? window.LuminaUtils.escapeHtml(value)
      : String(value ?? "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;");
  }

  function setOpen(next) {
    open = Boolean(next);
    if (!panel || !workspace) return;
    panel.hidden = !open;
    workspace.classList.toggle("has-artifact-panel", open);
    panel.classList.toggle("is-open", open);
    if (btnClose) btnClose.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) applyMode();
  }

  function ensureOpen() {
    if (!open) setOpen(true);
  }

  function formatTokens(n) {
    const value = Number(n) || 0;
    if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
    return String(value);
  }

  function applyMode() {
    const isContext = panelMode === "context";
    if (docsView) docsView.hidden = isContext;
    if (contextView) contextView.hidden = !isContext;
    if (rootSelect) rootSelect.hidden = isContext;
    if (btnRefresh) btnRefresh.hidden = isContext;
    btnModeDocs?.classList.toggle("is-active", !isContext);
    btnModeContext?.classList.toggle("is-active", isContext);
    btnModeDocs?.setAttribute("aria-pressed", isContext ? "false" : "true");
    btnModeContext?.setAttribute("aria-pressed", isContext ? "true" : "false");
    if (isContext) {
      if (titleEl) titleEl.textContent = "上下文";
      renderContextView();
    } else if (titleEl && !activeFile) {
      titleEl.textContent = "文档";
    }
  }

  function setMode(next) {
    panelMode = next === "context" ? "context" : "documents";
    try {
      localStorage.setItem("artifactPanelMode", panelMode);
    } catch {
      /* ignore */
    }
    ensureOpen();
    applyMode();
    if (panelMode === "documents") void renderTree();
  }

  function setContextSnapshot(snapshot, forThreadId) {
    const tid = String(forThreadId || threadId || "").trim() || "__default__";
    if (!snapshot || typeof snapshot !== "object") return;
    contextByThread.set(tid, snapshot);
    if (tid === (threadId || "__default__") && panelMode === "context") {
      renderContextView();
    }
  }

  function renderContextView() {
    if (!contextContentEl || !contextEmptyEl) return;
    const tid = threadId || "__default__";
    const snap = contextByThread.get(tid);
    if (!snap || !Array.isArray(snap.messages) || !snap.messages.length) {
      contextEmptyEl.hidden = false;
      contextContentEl.hidden = true;
      contextContentEl.innerHTML = "";
      if (metaEl) metaEl.textContent = "";
      return;
    }
    contextEmptyEl.hidden = true;
    contextContentEl.hidden = false;
    const usage = snap.usage || {};
    const total = snap.approx_total_tokens || usage.estimated_prompt_tokens || usage.prompt_tokens || 0;
    if (metaEl) {
      metaEl.textContent = `${snap.message_count || snap.messages.length} 条 · ~${formatTokens(total)} tok`;
    }
    const cacheHit = usage.cache_hit_tokens;
    const cacheMiss = usage.cache_miss_tokens;
    const cacheLine =
      cacheHit != null || cacheMiss != null
        ? `<span>cache ${formatTokens(cacheHit || 0)} / ${formatTokens(cacheMiss || 0)}</span>`
        : "";
    const compaction = snap.compaction || {};
    const compactLine =
      compaction.before_tokens != null && compaction.after_tokens != null
        ? `<span>压缩 ${formatTokens(compaction.before_tokens)}→${formatTokens(compaction.after_tokens)}</span>`
        : "";
    const msgs = snap.messages
      .map((msg, idx) => {
        const role = escapeHtml(msg.role || "unknown");
        const tokens = formatTokens(msg.approx_tokens || 0);
        const open = idx === 0 || idx >= snap.messages.length - 2 ? " open" : "";
        return (
          `<details class="artifact-context-msg"${open}>` +
          `<summary><span class="artifact-context-role">${role}</span>` +
          `<span class="artifact-context-tok">~${tokens}</span></summary>` +
          `<pre class="artifact-context-text">${escapeHtml(msg.content || "")}</pre>` +
          `</details>`
        );
      })
      .join("");
    contextContentEl.innerHTML =
      `<div class="artifact-context-usage">` +
      `<span>prompt ${formatTokens(usage.prompt_tokens || 0)}</span>` +
      `<span>completion ${formatTokens(usage.completion_tokens || 0)}</span>` +
      `<span>total ${formatTokens(usage.total_tokens || total)}</span>` +
      cacheLine +
      compactLine +
      `</div>` +
      `<div class="artifact-context-actions">` +
      `<button type="button" class="artifact-context-expand-btn" data-ctx-expand="1">全部展开</button>` +
      `<button type="button" class="artifact-context-expand-btn" data-ctx-expand="0">全部折叠</button>` +
      `</div>` +
      `<div class="artifact-context-list">${msgs}</div>`;
    contextContentEl.querySelectorAll("[data-ctx-expand]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const openAll = btn.getAttribute("data-ctx-expand") === "1";
        contextContentEl.querySelectorAll("details.artifact-context-msg").forEach((el) => {
          el.open = openAll;
        });
      });
    });
  }

  function noteFile(path, source) {
    const cleaned = String(path || "").trim();
    if (!cleaned) return;
    const name = basename(cleaned);
    const existing = sessionFiles.findIndex((item) => item.path === cleaned);
    const entry = { path: cleaned, name, source: source || "session" };
    if (existing >= 0) sessionFiles.splice(existing, 1);
    sessionFiles.unshift(entry);
    if (sessionFiles.length > 40) sessionFiles.length = 40;
    if (isPreviewable(cleaned)) {
      ensureOpen();
      void selectFile(cleaned);
    } else if (sessionFiles.length >= 2 || workspacePath) {
      ensureOpen();
      renderTree();
    }
  }

  function extractPaths(detail) {
    const text = String(detail || "");
    const found = [];
    for (const match of text.matchAll(/`([^`\n]+)`/g)) {
      const p = match[1].trim();
      if (p.includes("/") || p.includes("\\") || /\.\w+$/.test(p)) found.push(p);
    }
    const wrote = text.match(/to\s+(\/[^\s]+)/i);
    if (wrote?.[1]) found.push(wrote[1].trim());
    return [...new Set(found)];
  }

  function noteToolEvent(event) {
    const kind = String(event?.kind || "");
    const tool = String(event?.tool_name || "");
    if (kind !== "tool_started" && kind !== "tool_finished") return;
    if (kind === "tool_finished" && event?.success === false) return;

    const structured = Array.isArray(event?.paths)
      ? event.paths.map((p) => String(p || "").trim()).filter(Boolean)
      : [];
    if (structured.length) {
      for (const path of structured) noteFile(path, tool || "tool");
      return;
    }

    if (!WRITE_TOOLS.test(tool)) return;
    const detail = String(event?.detail || event?.message || "");
    const paths = extractPaths(detail);
    if (tool === "move" && paths.length >= 2) {
      noteFile(paths[paths.length - 1], "move");
      return;
    }
    for (const path of paths) noteFile(path, tool);
  }

  async function refreshContext() {
    try {
      const ctx = await window.SecretaryAPI.request(
        "GET",
        `/api/artifacts/context?thread_id=${encodeURIComponent(threadId || "")}`,
      );
      sandboxPath = String(ctx?.sandbox || "");
      workspacePath = String(ctx?.workspace || "") || workspacePath;
      const roots = Array.isArray(ctx?.roots) ? ctx.roots : [];
      if (rootSelect) {
        const prev = rootSelect.value;
        rootSelect.innerHTML = "";
        for (const root of roots) {
          const opt = document.createElement("option");
          opt.value = root.path;
          opt.textContent = root.label || root.id;
          rootSelect.appendChild(opt);
        }
        if (sessionFiles.length) {
          const opt = document.createElement("option");
          opt.value = "__session__";
          opt.textContent = "本轮产物";
          rootSelect.appendChild(opt);
        }
        if (prev && [...rootSelect.options].some((o) => o.value === prev)) {
          rootSelect.value = prev;
        } else if (workspacePath) {
          rootSelect.value = workspacePath;
        } else if (sessionFiles.length) {
          rootSelect.value = "__session__";
        } else if (sandboxPath) {
          rootSelect.value = sandboxPath;
        }
        activeRoot = rootSelect.value;
      }
    } catch (error) {
      console.warn("[artifacts] context failed", error);
    }
  }

  function renderSessionTree() {
    if (!treeEl) return;
    treeEl.innerHTML = "";
    if (!sessionFiles.length) {
      treeEl.innerHTML = `<p class="artifact-muted">暂无本轮产物</p>`;
      return;
    }
    const list = document.createElement("ul");
    list.className = "artifact-tree-list";
    for (const file of sessionFiles) {
      list.appendChild(makeTreeItem(file.path, file.name, "file", 0));
    }
    treeEl.appendChild(list);
  }

  function makeTreeItem(path, name, type, depth) {
    const li = document.createElement("li");
    li.className = `artifact-tree-item is-${type}`;
    li.style.setProperty("--depth", String(depth));
    if (path === activeFile) li.classList.add("is-active");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "artifact-tree-btn";
    btn.title = path;
    const icon = type === "dir" ? "📁" : extOf(path) === ".xlsx" || extOf(path) === ".xlsm" ? "📊" : "📄";
    btn.innerHTML = `<span class="artifact-tree-icon">${icon}</span><span class="artifact-tree-name">${escapeHtml(name)}</span>`;
    if (type === "file") {
      btn.addEventListener("click", () => {
        void selectFile(path);
      });
    } else {
      btn.disabled = true;
    }
    li.appendChild(btn);
    return li;
  }

  async function renderTree() {
    if (!treeEl) return;
    if (!open) return;
    if (activeRoot === "__session__" || (!activeRoot && sessionFiles.length && !workspacePath)) {
      renderSessionTree();
      return;
    }
    const root = activeRoot || workspacePath || sandboxPath;
    if (!root) {
      if (sessionFiles.length) {
        renderSessionTree();
        return;
      }
      treeEl.innerHTML = `<p class="artifact-muted">指定工作区或生成文档后显示文件树</p>`;
      return;
    }
    treeEl.innerHTML = `<p class="artifact-muted">加载中…</p>`;
    try {
      const data = await window.SecretaryAPI.request(
        "GET",
        `/api/artifacts/tree?path=${encodeURIComponent(root)}&thread_id=${encodeURIComponent(threadId || "")}&depth=3`,
      );
      const entries = Array.isArray(data?.entries) ? data.entries : [];
      treeEl.innerHTML = "";
      if (!entries.length) {
        treeEl.innerHTML = `<p class="artifact-muted">目录为空</p>`;
        return;
      }
      const list = document.createElement("ul");
      list.className = "artifact-tree-list";
      for (const entry of entries) {
        list.appendChild(
          makeTreeItem(entry.path, entry.name, entry.type, Number(entry.depth) || 0),
        );
      }
      treeEl.appendChild(list);
      if (data?.truncated) {
        const note = document.createElement("p");
        note.className = "artifact-muted";
        note.textContent = "已截断过深/过多条目";
        treeEl.appendChild(note);
      }
    } catch (error) {
      treeEl.innerHTML = `<p class="artifact-muted">无法读取目录</p>`;
      console.warn("[artifacts] tree failed", error);
    }
  }

  function rawUrl(path) {
    return `/api/artifacts/raw?path=${encodeURIComponent(path)}&thread_id=${encodeURIComponent(threadId || "")}`;
  }

  function renderMarkdownBlock(text, className) {
    const html =
      window.LuminaMarkdown?.render?.(text || "") || `<pre>${escapeHtml(text || "")}</pre>`;
    return `<article class="${className} markdown">${html}</article>`;
  }

  function renderHtmlPreview(htmlSource) {
    const wrap = document.createElement("div");
    wrap.className = "artifact-html-wrap";
    const iframe = document.createElement("iframe");
    iframe.className = "artifact-embed";
    iframe.title = "HTML preview";
    iframe.setAttribute("sandbox", "allow-same-origin");
    const cleaned =
      typeof window.DOMPurify?.sanitize === "function"
        ? window.DOMPurify.sanitize(String(htmlSource || ""), {
            WHOLE_DOCUMENT: true,
            ADD_TAGS: ["html", "head", "body", "meta", "link", "style"],
            ADD_ATTR: ["target", "rel", "class", "style", "href", "src", "alt"],
          })
        : escapeHtml(String(htmlSource || ""));
    iframe.srcdoc = cleaned;
    wrap.appendChild(iframe);
    return wrap;
  }

  function renderPdfPreview(path, excerpt) {
    const wrap = document.createElement("div");
    wrap.className = "artifact-pdf-wrap";
    const iframe = document.createElement("iframe");
    iframe.className = "artifact-embed";
    iframe.title = "PDF preview";
    iframe.src = rawUrl(path);
    wrap.appendChild(iframe);
    if (excerpt) {
      const details = document.createElement("details");
      details.className = "artifact-excerpt";
      details.innerHTML = `<summary>文本摘录</summary><pre class="artifact-text">${escapeHtml(excerpt)}</pre>`;
      wrap.appendChild(details);
    }
    return wrap;
  }

  function renderTable(table) {
    const sheets = Array.isArray(table?.sheets) ? table.sheets : [];
    if (!sheets.length && Array.isArray(table?.rows)) {
      sheets.push({ name: "Sheet", rows: table.rows, truncated: table.truncated });
    }
    return sheets
      .map((sheet) => {
        const rows = Array.isArray(sheet.rows) ? sheet.rows : [];
        if (!rows.length) return `<section class="artifact-sheet"><h4>${escapeHtml(sheet.name || "Sheet")}</h4><p class="artifact-muted">空表</p></section>`;
        const colCount = Math.max(...rows.map((r) => (Array.isArray(r) ? r.length : 0)));
        const body = rows
          .map((row, rowIdx) => {
            const cells = Array.from({ length: colCount }, (_, ci) => {
              const value = Array.isArray(row) ? String(row[ci] ?? "") : "";
              if (rowIdx === 0) return `<th>${escapeHtml(value)}</th>`;
              return `<td>${escapeHtml(value)}</td>`;
            }).join("");
            return `<tr>${cells}</tr>`;
          })
          .join("");
        const trunc = sheet.truncated ? `<p class="artifact-muted">已截断后续行（仅显示前 ${rows.length} 行）</p>` : "";
        const meta = `<p class="artifact-muted">${rows.length} 行 × ${colCount} 列</p>`;
        return `<section class="artifact-sheet"><h4>${escapeHtml(sheet.name || "Sheet")}</h4>${meta}<div class="artifact-table-wrap"><table class="artifact-table">${body}</table></div>${trunc}</section>`;
      })
      .join("");
  }

  function paintPreview(kind, data, path) {
    previewEl.innerHTML = "";
    if (kind === "table") {
      previewEl.innerHTML = renderTable(data.table);
      return;
    }
    if (kind === "markdown") {
      previewEl.innerHTML = renderMarkdownBlock(data.text, "artifact-md");
      return;
    }
    if (kind === "docx") {
      previewEl.innerHTML =
        `<div class="artifact-kind-chip">DOCX</div>` +
        renderMarkdownBlock(data.text, "artifact-docx");
      return;
    }
    if (kind === "html") {
      previewEl.appendChild(renderHtmlPreview(data.text));
      return;
    }
    if (kind === "pdf") {
      previewEl.appendChild(renderPdfPreview(path, data.text || ""));
      return;
    }
    if (kind === "text") {
      previewEl.innerHTML = `<pre class="artifact-text">${escapeHtml(data.text || "")}</pre>`;
      return;
    }
    previewEl.innerHTML = `<p class="artifact-muted">暂不支持预览此类型（${escapeHtml(kind || data.ext || "")}）</p>`;
  }

  async function selectFile(path) {
    activeFile = path;
    renderTree();
    if (!previewEl) return;
    ensureOpen();
    if (titleEl) titleEl.textContent = basename(path);
    if (metaEl) metaEl.textContent = path;
    if (emptyEl) emptyEl.hidden = true;
    previewEl.innerHTML = `<p class="artifact-muted">加载预览…</p>`;
    if (btnOpenExternal) {
      btnOpenExternal.hidden = false;
      btnOpenExternal.dataset.path = path;
    }
    try {
      const data = await window.SecretaryAPI.request(
        "GET",
        `/api/artifacts/file?path=${encodeURIComponent(path)}&thread_id=${encodeURIComponent(threadId || "")}`,
      );
      paintPreview(String(data?.kind || ""), data, path);
      if (metaEl) {
        const size = Number(data.size) || 0;
        const kind = String(data.kind || extOf(path).replace(".", "") || "file").toUpperCase();
        metaEl.textContent = `${kind} · ${(size / 1024).toFixed(1)} KB`;
      }
    } catch (error) {
      previewEl.innerHTML = `<p class="artifact-muted">预览失败：${escapeHtml(error?.message || error)}</p>`;
    }
  }

  async function syncFromWorkspace(path) {
    workspacePath = String(path || "").trim();
    await refreshContext();
    if (workspacePath) {
      activeRoot = workspacePath;
      if (rootSelect) rootSelect.value = workspacePath;
      ensureOpen();
      await renderTree();
    } else if (!sessionFiles.length) {
      setOpen(false);
    } else {
      await renderTree();
    }
  }

  async function setThread(nextId) {
    threadId = String(nextId || "");
    sessionFiles = [];
    activeFile = "";
    if (previewEl) previewEl.innerHTML = "";
    if (titleEl) titleEl.textContent = panelMode === "context" ? "上下文" : "文档";
    if (metaEl) metaEl.textContent = "";
    if (emptyEl) emptyEl.hidden = false;
    if (btnOpenExternal) btnOpenExternal.hidden = true;
    await refreshContext();
    if (panelMode === "context") {
      ensureOpen();
      applyMode();
      return;
    }
    if (workspacePath || sandboxPath) {
      // Keep closed until there is something to show, unless workspace is set.
      if (workspacePath) {
        ensureOpen();
        await renderTree();
      }
    } else {
      setOpen(false);
    }
  }

  btnClose?.addEventListener("click", () => setOpen(false));
  btnRefresh?.addEventListener("click", () => {
    void refreshContext().then(renderTree);
  });
  rootSelect?.addEventListener("change", () => {
    activeRoot = rootSelect.value;
    void renderTree();
  });
  btnModeDocs?.addEventListener("click", () => setMode("documents"));
  btnModeContext?.addEventListener("click", () => setMode("context"));
  btnOpenExternal?.addEventListener("click", () => {
    const path = btnOpenExternal.dataset.path;
    if (!path) return;
    // Reveal via file:// — Electron may block; still useful in browser/dev.
    window.open(`file://${path}`, "_blank");
  });

  // 宽度拖拽：左边框把手，宽度记忆到 localStorage
  const resizeHandle = document.createElement("div");
  resizeHandle.className = "artifact-resize";
  resizeHandle.setAttribute("aria-hidden", "true");
  panel.appendChild(resizeHandle);
  try {
    const savedWidth = Number(localStorage.getItem("artifactPanelWidth") || 0);
    if (savedWidth >= 240) panel.style.width = `${savedWidth}px`;
  } catch (_e) {
    /* ignore */
  }
  resizeHandle.addEventListener("mousedown", (event) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = panel.offsetWidth;
    const onMove = (ev) => {
      const next = Math.min(
        Math.max(startWidth + (startX - ev.clientX), 240),
        Math.floor(window.innerWidth * 0.6),
      );
      panel.style.width = `${next}px`;
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      try {
        localStorage.setItem("artifactPanelWidth", String(panel.offsetWidth));
      } catch (_e) {
        /* ignore */
      }
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });

  applyMode();

  window.LuminaArtifacts = {
    noteToolEvent,
    noteFile,
    setWorkspace: syncFromWorkspace,
    setThread,
    setContextSnapshot,
    setMode,
    open: () => {
      ensureOpen();
      if (panelMode === "context") applyMode();
      else void refreshContext().then(renderTree);
    },
    preview: (path) => {
      setMode("documents");
      ensureOpen();
      void selectFile(String(path || ""));
    },
    openContext: () => setMode("context"),
    close: () => setOpen(false),
    isOpen: () => open,
  };
})();
