/** Workflow list + run panel (F26 — canvas editor comes later). */
(function () {
  "use strict";

  const panel = document.getElementById("workflows-panel");
  const backdrop = document.getElementById("workflows-backdrop");
  const navEl = document.getElementById("workflows-nav");
  const contentEl = document.getElementById("workflows-content");
  const openBtn = document.getElementById("btn-workflows");
  const closeBtn = document.getElementById("btn-close-workflows");
  const newSampleBtn = document.getElementById("btn-workflow-new-sample");

  if (!panel || !backdrop || !navEl || !contentEl || !openBtn) {
    return;
  }

  let workflows = [];
  let activeName = "";
  let activeDef = null;
  let lastResult = null;

  function t(key) {
    return window.LuminaI18n?.t?.(key) || key;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  openBtn.addEventListener("click", openWorkflows);
  closeBtn?.addEventListener("click", closeWorkflows);
  backdrop.addEventListener("click", closeWorkflows);
  newSampleBtn?.addEventListener("click", createSample);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && panel && !panel.hidden) {
      closeWorkflows();
    }
  });

  async function openWorkflows() {
    panel.hidden = false;
    backdrop.hidden = false;
    await refreshList();
  }

  function closeWorkflows() {
    panel.hidden = true;
    backdrop.hidden = true;
  }

  async function refreshList() {
    contentEl.innerHTML = `<p class="muted">${escapeHtml(t("settings.loading"))}</p>`;
    try {
      const data = await window.SecretaryAPI.request("GET", "/api/workflows");
      workflows = Array.isArray(data?.workflows) ? data.workflows : [];
      if (!activeName && workflows.length) {
        activeName = workflows[0].name;
      }
      if (activeName && !workflows.some((item) => item.name === activeName)) {
        activeName = workflows[0]?.name || "";
        activeDef = null;
        lastResult = null;
      }
      renderNav();
      if (activeName) {
        await loadActive();
      } else {
        renderEmpty();
      }
    } catch (error) {
      contentEl.innerHTML = `<p class="muted">${escapeHtml(error.message || String(error))}</p>`;
    }
  }

  function renderNav() {
    navEl.innerHTML = "";
    if (!workflows.length) {
      navEl.innerHTML = `<p class="muted workflows-nav-empty">${escapeHtml(t("workflows.empty"))}</p>`;
      return;
    }
    for (const item of workflows) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `settings-nav-item${item.name === activeName ? " active" : ""}`;
      btn.textContent = item.name;
      btn.addEventListener("click", async () => {
        activeName = item.name;
        lastResult = null;
        renderNav();
        await loadActive();
      });
      navEl.appendChild(btn);
    }
  }

  function renderEmpty() {
    contentEl.innerHTML = `
      <div class="workflows-empty">
        <p>${escapeHtml(t("workflows.empty"))}</p>
        <p class="muted">${escapeHtml(t("workflows.canvasHint"))}</p>
        <button type="button" class="btn-text" id="btn-workflow-empty-sample">${escapeHtml(t("workflows.newSample"))}</button>
      </div>`;
    document
      .getElementById("btn-workflow-empty-sample")
      ?.addEventListener("click", createSample);
  }

  async function loadActive() {
    if (!activeName) {
      renderEmpty();
      return;
    }
    contentEl.innerHTML = `<p class="muted">${escapeHtml(t("settings.loading"))}</p>`;
    try {
      activeDef = await window.SecretaryAPI.request("GET", `/api/workflows/${encodeURIComponent(activeName)}`);
      renderDetail();
    } catch (error) {
      contentEl.innerHTML = `<p class="muted">${escapeHtml(error.message || String(error))}</p>`;
    }
  }

  function renderDetail() {
    const nodes = Array.isArray(activeDef?.nodes) ? activeDef.nodes : [];
    const edges = Array.isArray(activeDef?.edges) ? activeDef.edges : [];
    const inputKeys = Object.keys(activeDef?.inputs_schema || {});
    const defaultInputs = {};
    for (const key of inputKeys) {
      defaultInputs[key] = key === "topic" ? "Lumina" : "";
    }
    const inputsJson = JSON.stringify(defaultInputs, null, 2);
    const nodeLines = nodes
      .map((node) => `${node.id} · ${node.kind}`)
      .join("\n");
    const edgeLines = edges
      .map((edge) => `${edge.from} → ${edge.to}${edge.port && edge.port !== "default" ? ` [${edge.port}]` : ""}`)
      .join("\n");

    contentEl.innerHTML = `
      <div class="workflows-detail">
        <header class="workflows-detail-head">
          <h2>${escapeHtml(activeDef.name)}</h2>
          <span class="muted">v${escapeHtml(String(activeDef.version || 1))}</span>
        </header>
        <p class="muted">${escapeHtml(t("workflows.canvasHint"))}</p>
        <section class="workflows-section">
          <h3>${escapeHtml(t("workflows.nodes"))}</h3>
          <pre class="workflows-pre">${escapeHtml(nodeLines || "(none)")}</pre>
          <pre class="workflows-pre">${escapeHtml(edgeLines || "(no edges)")}</pre>
        </section>
        <section class="workflows-section">
          <label for="workflow-inputs">${escapeHtml(t("workflows.inputs"))}</label>
          <textarea id="workflow-inputs" class="workflows-inputs" rows="6" spellcheck="false">${escapeHtml(inputsJson)}</textarea>
        </section>
        <div class="workflows-actions">
          <button type="button" class="btn-run" id="btn-workflow-run">${escapeHtml(t("workflows.run"))}</button>
          <button type="button" class="btn-text" id="btn-workflow-delete">${escapeHtml(t("workflows.delete"))}</button>
        </div>
        <section class="workflows-section" id="workflow-result-section" ${lastResult ? "" : "hidden"}>
          <h3>${escapeHtml(t("workflows.result"))}</h3>
          <pre class="workflows-pre" id="workflow-result-pre">${escapeHtml(
            lastResult ? JSON.stringify(lastResult, null, 2) : ""
          )}</pre>
        </section>
      </div>`;

    document.getElementById("btn-workflow-run")?.addEventListener("click", runActive);
    document.getElementById("btn-workflow-delete")?.addEventListener("click", deleteActive);
  }

  async function runActive() {
    const textarea = document.getElementById("workflow-inputs");
    let inputs = {};
    try {
      inputs = JSON.parse(textarea?.value || "{}");
    } catch (error) {
      lastResult = { status: "failed", error: `Invalid JSON: ${error.message}` };
      renderDetail();
      return;
    }
    const runBtn = document.getElementById("btn-workflow-run");
    if (runBtn) {
      runBtn.disabled = true;
      runBtn.textContent = "…";
    }
    try {
      lastResult = await window.SecretaryAPI.request(
        "POST",
        `/api/workflows/${encodeURIComponent(activeName)}/run`,
        { inputs }
      );
    } catch (error) {
      lastResult = { status: "failed", error: error.message || String(error) };
    }
    renderDetail();
  }

  async function deleteActive() {
    if (!activeName) return;
    if (!window.confirm(`Delete workflow “${activeName}”?`)) return;
    await window.SecretaryAPI.request("DELETE", `/api/workflows/${encodeURIComponent(activeName)}`);
    activeName = "";
    activeDef = null;
    lastResult = null;
    await refreshList();
  }

  async function createSample() {
    const name = `sample_${Date.now().toString(36).slice(-6)}`;
    const payload = {
      name,
      version: 1,
      inputs_schema: { topic: { type: "string" } },
      outputs_schema: { summary: { type: "string" } },
      nodes: [
        {
          id: "draft",
          kind: "agent",
          config: { prompt_template: "用三条要点介绍：{{topic}}" },
          inputs_schema: {},
          outputs_schema: { summary: "string" },
          on_failure: "stop",
        },
        {
          id: "summary",
          kind: "agent",
          config: { prompt_template: "把下面内容压成一句话：{{draft.summary}}" },
          inputs_schema: {},
          outputs_schema: { summary: "string" },
          on_failure: "stop",
        },
      ],
      edges: [{ from: "draft", to: "summary", port: "default" }],
    };
    await window.SecretaryAPI.request("PUT", `/api/workflows/${encodeURIComponent(name)}`, payload);
    activeName = name;
    lastResult = null;
    await refreshList();
  }

  window.WorkflowsModule = { open: openWorkflows, close: closeWorkflows };
})();
