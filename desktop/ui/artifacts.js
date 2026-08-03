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
  const workspace = document.querySelector(".workspace");

  /** @type {{ path: string, name: string, source: string }[]} */
  let sessionFiles = [];
  let threadId = "";
  let workspacePath = "";
  let sandboxPath = "";
  let activeRoot = "";
  let activeFile = "";
  let open = false;

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

  function escapeHtml(text) {
    return window.LuminaUtils?.escapeHtml
      ? window.LuminaUtils.escapeHtml(text)
      : String(text || "")
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
  }

  function ensureOpen() {
    if (!open) setOpen(true);
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
    if (!WRITE_TOOLS.test(tool)) return;
    if (kind !== "tool_started" && kind !== "tool_finished") return;
    if (kind === "tool_finished" && event?.success === false) return;
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
        const body = rows
          .map((row, rowIdx) => {
            const cells = (Array.isArray(row) ? row : []).map((cell) => {
              const tag = rowIdx === 0 ? "th" : "td";
              return `<${tag}>${escapeHtml(cell)}</${tag}>`;
            });
            return `<tr>${cells.join("")}</tr>`;
          })
          .join("");
        const trunc = sheet.truncated ? `<p class="artifact-muted">已截断行数</p>` : "";
        return `<section class="artifact-sheet"><h4>${escapeHtml(sheet.name || "Sheet")}</h4><div class="artifact-table-wrap"><table class="artifact-table">${body}</table></div>${trunc}</section>`;
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
    if (titleEl) titleEl.textContent = "文档";
    if (metaEl) metaEl.textContent = "";
    if (emptyEl) emptyEl.hidden = false;
    if (btnOpenExternal) btnOpenExternal.hidden = true;
    await refreshContext();
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
  btnOpenExternal?.addEventListener("click", () => {
    const path = btnOpenExternal.dataset.path;
    if (!path) return;
    // Reveal via file:// — Electron may block; still useful in browser/dev.
    window.open(`file://${path}`, "_blank");
  });

  window.LuminaArtifacts = {
    noteToolEvent,
    noteFile,
    setWorkspace: syncFromWorkspace,
    setThread,
    open: () => {
      ensureOpen();
      void refreshContext().then(renderTree);
    },
    close: () => setOpen(false),
    isOpen: () => open,
  };
})();
