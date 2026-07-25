/** Workflow list + Drawflow canvas editor (F26). */
(function () {
  "use strict";

  const panel = document.getElementById("workflows-panel");
  const backdrop = document.getElementById("workflows-backdrop");
  const navEl = document.getElementById("workflows-nav");
  const contentEl = document.getElementById("workflows-content");
  const editorEl = document.getElementById("workflows-editor");
  const canvasEl = document.getElementById("workflow-drawflow");
  const inspectorEl = document.getElementById("workflows-inspector");
  const openBtn = document.getElementById("btn-workflows");
  const closeBtn = document.getElementById("btn-close-workflows");
  const newSampleBtn = document.getElementById("btn-workflow-new-sample");
  const fromTemplateBtn = document.getElementById("btn-workflow-from-template");
  const saveBtn = document.getElementById("btn-workflow-save");
  const runBtn = document.getElementById("btn-workflow-run");
  const Graph = window.LuminaWorkflowGraph;

  if (!panel || !backdrop || !navEl || !contentEl || !openBtn || !Graph) {
    return;
  }

  let workflows = [];
  let activeName = "";
  let activeDef = null;
  let lastResult = null;
  let editor = null;
  let selectedDfId = null;
  let nodeCounter = 0;
  let suppressSelect = false;

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
  fromTemplateBtn?.addEventListener("click", () => void createFromTemplate());
  saveBtn?.addEventListener("click", saveActive);
  runBtn?.addEventListener("click", runActive);

  document.querySelectorAll(".workflows-palette-btn").forEach((btn) => {
    btn.addEventListener("click", () => addPaletteNode(btn.dataset.kind || "agent"));
  });

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
    destroyEditor();
    panel.hidden = true;
    backdrop.hidden = true;
  }

  function setEditorVisible(visible) {
    if (editorEl) editorEl.hidden = !visible;
    if (contentEl) contentEl.hidden = visible;
    if (saveBtn) saveBtn.hidden = !visible;
    if (runBtn) runBtn.hidden = !visible;
  }

  async function refreshList() {
    setEditorVisible(false);
    contentEl.hidden = false;
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
        if (item.name === activeName) return;
        activeName = item.name;
        lastResult = null;
        selectedDfId = null;
        renderNav();
        await loadActive();
      });
      navEl.appendChild(btn);
    }
  }

  function renderEmpty() {
    destroyEditor();
    setEditorVisible(false);
    contentEl.hidden = false;
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
    try {
      activeDef = await window.SecretaryAPI.request(
        "GET",
        `/api/workflows/${encodeURIComponent(activeName)}`
      );
      mountEditor(activeDef);
    } catch (error) {
      destroyEditor();
      setEditorVisible(false);
      contentEl.hidden = false;
      contentEl.innerHTML = `<p class="muted">${escapeHtml(error.message || String(error))}</p>`;
    }
  }

  function destroyEditor() {
    if (editor) {
      try {
        editor.clear();
      } catch (_) {
        /* ignore */
      }
      editor = null;
    }
    if (canvasEl) {
      canvasEl.innerHTML = "";
    }
    selectedDfId = null;
  }

  function mountEditor(workflow) {
    if (!canvasEl || typeof Drawflow !== "function") {
      contentEl.hidden = false;
      contentEl.innerHTML = `<p class="muted">Drawflow failed to load</p>`;
      return;
    }
    destroyEditor();
    setEditorVisible(true);
    editor = new Drawflow(canvasEl);
    editor.reroute = true;
    editor.start();
    const payload = Graph.workflowToDrawflow(workflow);
    suppressSelect = true;
    editor.import(payload);
    suppressSelect = false;
    nodeCounter = Object.keys(payload.drawflow.Home.data || {}).length;

    editor.on("nodeSelected", (id) => {
      if (suppressSelect) return;
      selectedDfId = String(id);
      renderInspector();
      highlightSelection();
    });
    editor.on("nodeUnselected", () => {
      selectedDfId = null;
      renderInspector();
      highlightSelection();
    });
    editor.on("nodeRemoved", () => {
      selectedDfId = null;
      renderInspector();
    });

    renderInspector();
    applyRunHighlights(lastResult);
  }

  function currentMeta() {
    return {
      name: activeDef?.name || activeName,
      version: activeDef?.version || 1,
      inputs_schema: activeDef?.inputs_schema || {},
      outputs_schema: activeDef?.outputs_schema || {},
    };
  }

  function exportWorkflow() {
    if (!editor) return null;
    return Graph.drawflowToWorkflow(editor.export(), currentMeta());
  }

  function addPaletteNode(kind) {
    if (!editor || !activeDef) return;
    nodeCounter += 1;
    const spec = Graph.newNodeSpec(kind, nodeCounter);
    const io = Graph.kindIo(kind);
    const dfId = editor.addNode(
      kind,
      io.inputs,
      io.outputs,
      80 + (nodeCounter % 4) * 40,
      100 + (nodeCounter % 3) * 50,
      `wf-${kind}`,
      {
        workflowId: spec.id,
        kind: spec.kind,
        config: spec.config,
        on_failure: spec.on_failure,
        inputs_schema: spec.inputs_schema,
        outputs_schema: spec.outputs_schema,
      },
      Graph.nodeHtml(kind, Graph.defaultLabel(spec))
    );
    selectedDfId = String(dfId);
    renderInspector();
    highlightSelection();
  }

  function getSelectedNodeData() {
    if (!editor || !selectedDfId) return null;
    const raw = editor.getNodeFromId(selectedDfId);
    return raw || null;
  }

  function renderInspector() {
    if (!inspectorEl) return;
    const node = getSelectedNodeData();
    if (!node) {
      inspectorEl.innerHTML = `
        <div class="workflows-inspector-empty">
          <p class="muted">${escapeHtml(t("workflows.selectNode"))}</p>
          <p class="muted">${escapeHtml(t("workflows.canvasHint"))}</p>
          <section class="workflows-section">
            <label for="workflow-inputs">${escapeHtml(t("workflows.inputs"))}</label>
            <textarea id="workflow-inputs" class="workflows-inputs" rows="5" spellcheck="false">${escapeHtml(
              defaultInputsJson()
            )}</textarea>
          </section>
          ${
            lastResult
              ? `<section class="workflows-section"><h3>${escapeHtml(
                  t("workflows.result")
                )}</h3>${
                  lastResult.status === "paused"
                    ? `<p class="muted">${escapeHtml(
                        lastResult.pause_prompt || "等待确认"
                      )}</p>
                <label>备注
                  <input id="wf-resume-note" type="text" value="" />
                </label>
                <div class="workflows-actions">
                  <button type="button" class="btn-run" id="btn-wf-approve">${escapeHtml(
                    t("workflows.approve")
                  )}</button>
                  <button type="button" class="btn-text" id="btn-wf-reject">${escapeHtml(
                    t("workflows.reject")
                  )}</button>
                </div>`
                    : ""
                }<pre class="workflows-pre">${escapeHtml(
                  JSON.stringify(lastResult, null, 2)
                )}</pre></section>`
              : ""
          }
          <button type="button" class="btn-text" id="btn-workflow-delete">${escapeHtml(
            t("workflows.delete")
          )}</button>
        </div>`;
      document.getElementById("btn-workflow-delete")?.addEventListener("click", deleteActive);
      document.getElementById("btn-wf-approve")?.addEventListener("click", () =>
        void resumeActive(true),
      );
      document.getElementById("btn-wf-reject")?.addEventListener("click", () =>
        void resumeActive(false),
      );
      return;
    }

    const data = node.data || {};
    const kind = data.kind || "agent";
    const config = data.config || {};
    let fields = "";
    if (kind === "skill") {
      fields = `
        <label>skill_name
          <input id="wf-field-skill" type="text" value="${escapeHtml(config.skill_name || "")}" />
        </label>`;
    } else if (kind === "agent") {
      const mode = config.mode === "agent" ? "agent" : "llm";
      const profile = config.profile === "build" ? "build" : "ask";
      fields = `
        <label>mode
          <select id="wf-field-mode">
            <option value="llm"${mode === "llm" ? " selected" : ""}>llm（单次补全）</option>
            <option value="agent"${mode === "agent" ? " selected" : ""}>agent（AgentLoop）</option>
          </select>
        </label>
        <label>profile
          <select id="wf-field-profile">
            <option value="ask"${profile === "ask" ? " selected" : ""}>ask（只读工具）</option>
            <option value="build"${profile === "build" ? " selected" : ""}>build（可写/shell）</option>
          </select>
        </label>
        <label>prompt_template
          <textarea id="wf-field-prompt" rows="5" spellcheck="false">${escapeHtml(
            config.prompt_template || ""
          )}</textarea>
        </label>
        <label class="wf-check">
          <input id="wf-field-confirm" type="checkbox"${
            config.confirm_before ? " checked" : ""
          } /> 运行前确认 (confirm_before)
        </label>
        <label>confirm_prompt
          <input id="wf-field-confirm-prompt" type="text" value="${escapeHtml(
            config.confirm_prompt || ""
          )}" />
        </label>`;
    } else if (kind === "human_review") {
      fields = `
        <label>prompt
          <textarea id="wf-field-review-prompt" rows="3" spellcheck="false">${escapeHtml(
            config.prompt || "请确认后继续"
          )}</textarea>
        </label>`;
    } else if (kind === "branch") {
      const cond = config.condition || {};
      fields = `
        <label>path
          <input id="wf-field-path" type="text" value="${escapeHtml(cond.path || "")}" />
        </label>
        <label>op
          <select id="wf-field-op">
            <option value="eq"${cond.op === "eq" ? " selected" : ""}>eq</option>
            <option value="neq"${cond.op === "neq" ? " selected" : ""}>neq</option>
            <option value="contains"${cond.op === "contains" ? " selected" : ""}>contains</option>
          </select>
        </label>
        <label>value
          <input id="wf-field-value" type="text" value="${escapeHtml(
            cond.value == null ? "" : String(cond.value)
          )}" />
        </label>`;
    }

    inspectorEl.innerHTML = `
      <div class="workflows-inspector-form">
        <header class="workflows-detail-head">
          <h2>${escapeHtml(data.workflowId || "")}</h2>
          <span class="muted">${escapeHtml(kind)}</span>
        </header>
        <label>id
          <input id="wf-field-id" type="text" value="${escapeHtml(data.workflowId || "")}" />
        </label>
        <label>on_failure
          <select id="wf-field-failure">
            <option value="stop"${data.on_failure !== "continue" ? " selected" : ""}>stop</option>
            <option value="continue"${data.on_failure === "continue" ? " selected" : ""}>continue</option>
          </select>
        </label>
        ${fields}
        <div class="workflows-actions">
          <button type="button" class="btn-run" id="btn-wf-apply">应用</button>
          <button type="button" class="btn-text" id="btn-wf-remove-node">移除节点</button>
        </div>
        <section class="workflows-section">
          <label for="workflow-inputs">${escapeHtml(t("workflows.inputs"))}</label>
          <textarea id="workflow-inputs" class="workflows-inputs" rows="4" spellcheck="false">${escapeHtml(
            defaultInputsJson()
          )}</textarea>
        </section>
        ${
          lastResult
            ? `<section class="workflows-section"><h3>${escapeHtml(
                t("workflows.result")
              )}</h3>${
                lastResult.status === "paused"
                  ? `<p class="muted">${escapeHtml(
                      lastResult.pause_prompt || "等待确认"
                    )}</p>
                <label>备注
                  <input id="wf-resume-note" type="text" value="" />
                </label>
                <div class="workflows-actions">
                  <button type="button" class="btn-run" id="btn-wf-approve">${escapeHtml(
                    t("workflows.approve")
                  )}</button>
                  <button type="button" class="btn-text" id="btn-wf-reject">${escapeHtml(
                    t("workflows.reject")
                  )}</button>
                </div>`
                  : ""
              }<pre class="workflows-pre">${escapeHtml(
                JSON.stringify(lastResult, null, 2)
              )}</pre></section>`
            : ""
        }
        <button type="button" class="btn-text" id="btn-workflow-delete">${escapeHtml(
          t("workflows.delete")
        )}</button>
      </div>`;

    document.getElementById("btn-wf-apply")?.addEventListener("click", applyInspector);
    document.getElementById("btn-wf-approve")?.addEventListener("click", () =>
      void resumeActive(true),
    );
    document.getElementById("btn-wf-reject")?.addEventListener("click", () =>
      void resumeActive(false),
    );
    document.getElementById("btn-wf-remove-node")?.addEventListener("click", () => {
      if (!editor || !selectedDfId) return;
      editor.removeNodeId(`node-${selectedDfId}`);
      selectedDfId = null;
      renderInspector();
    });
    document.getElementById("btn-workflow-delete")?.addEventListener("click", deleteActive);
  }

  function defaultInputsJson() {
    const inputKeys = Object.keys(activeDef?.inputs_schema || {});
    const defaultInputs = {};
    for (const key of inputKeys) {
      defaultInputs[key] = key === "topic" ? "Lumina" : "";
    }
    return JSON.stringify(defaultInputs, null, 2);
  }

  function applyInspector() {
    if (!editor || !selectedDfId) return;
    const node = editor.getNodeFromId(selectedDfId);
    if (!node) return;
    const data = { ...(node.data || {}) };
    const config = { ...(data.config || {}) };
    const newId = document.getElementById("wf-field-id")?.value?.trim() || data.workflowId;
    data.workflowId = newId;
    data.on_failure = document.getElementById("wf-field-failure")?.value || "stop";
    if (data.kind === "skill") {
      config.skill_name = document.getElementById("wf-field-skill")?.value?.trim() || "";
    } else if (data.kind === "agent") {
      config.mode = document.getElementById("wf-field-mode")?.value || "llm";
      config.profile = document.getElementById("wf-field-profile")?.value || "ask";
      config.prompt_template = document.getElementById("wf-field-prompt")?.value || "";
      config.confirm_before = Boolean(document.getElementById("wf-field-confirm")?.checked);
      config.confirm_prompt =
        document.getElementById("wf-field-confirm-prompt")?.value?.trim() || "";
    } else if (data.kind === "human_review") {
      config.prompt =
        document.getElementById("wf-field-review-prompt")?.value?.trim() || "请确认后继续";
    } else if (data.kind === "branch") {
      config.condition = {
        type: "expr",
        path: document.getElementById("wf-field-path")?.value?.trim() || "",
        op: document.getElementById("wf-field-op")?.value || "eq",
        value: document.getElementById("wf-field-value")?.value || "",
      };
      config.true_port = config.true_port || "yes";
      config.false_port = config.false_port || "no";
      config.ports = config.ports || ["yes", "no"];
    }
    data.config = config;
    editor.updateNodeDataFromId(selectedDfId, data);
    // Refresh node HTML label
    const el = canvasEl.querySelector(`#node-${selectedDfId} .drawflow_content_node`);
    if (el) {
      el.innerHTML = Graph.nodeHtml(data.kind, Graph.defaultLabel({ id: newId, kind: data.kind, config }));
    }
  }

  function highlightSelection() {
    canvasEl?.querySelectorAll(".drawflow-node").forEach((el) => {
      el.classList.toggle("wf-selected", el.id === `node-${selectedDfId}`);
    });
  }

  function applyRunHighlights(result) {
    canvasEl?.querySelectorAll(".drawflow-node").forEach((el) => {
      el.classList.remove("wf-run-ok", "wf-run-fail", "wf-run-skip", "wf-run-active");
    });
    if (!result || !editor) return;
    const steps = Array.isArray(result.steps) ? result.steps : [];
    const byWorkflowId = {};
    const exported = editor.export()?.drawflow?.Home?.data || {};
    for (const item of Object.values(exported)) {
      const wid = item.data?.workflowId;
      if (wid) byWorkflowId[wid] = item.id;
    }
    for (const step of steps) {
      const dfId = byWorkflowId[step.node_id];
      if (!dfId) continue;
      const el = canvasEl.querySelector(`#node-${dfId}`);
      if (!el) continue;
      if (step.status === "completed") el.classList.add("wf-run-ok");
      else if (step.status === "failed") el.classList.add("wf-run-fail");
      else if (step.status === "skipped") el.classList.add("wf-run-skip");
      else if (step.status === "paused") el.classList.add("wf-run-active");
    }
  }

  async function resumeActive(approved) {
    const runId = lastResult?.run_id;
    if (!runId) return;
    const note = document.getElementById("wf-resume-note")?.value || "";
    try {
      lastResult = await window.SecretaryAPI.request(
        "POST",
        `/api/workflows/runs/${encodeURIComponent(runId)}/resume`,
        { approved: Boolean(approved), note },
      );
    } catch (error) {
      lastResult = { status: "failed", error: error.message || String(error) };
    }
    renderInspector();
    applyRunHighlights(lastResult);
  }

  async function saveActive() {
    if (!editor || !activeName) return;
    applyInspectorQuiet();
    const payload = exportWorkflow();
    if (!payload) return;
    payload.name = activeName;
    activeDef = await window.SecretaryAPI.request(
      "PUT",
      `/api/workflows/${encodeURIComponent(activeName)}`,
      payload
    );
    if (saveBtn) {
      const prev = saveBtn.textContent;
      saveBtn.textContent = t("workflows.saved");
      setTimeout(() => {
        saveBtn.textContent = prev;
      }, 900);
    }
  }

  function applyInspectorQuiet() {
    if (selectedDfId && document.getElementById("wf-field-id")) {
      applyInspector();
    }
  }

  async function runActive() {
    if (!activeName) return;
    await saveActive();
    const textarea = document.getElementById("workflow-inputs");
    let inputs = {};
    try {
      inputs = JSON.parse(textarea?.value || "{}");
    } catch (error) {
      lastResult = { status: "failed", error: `Invalid JSON: ${error.message}` };
      renderInspector();
      return;
    }
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
    if (runBtn) {
      runBtn.disabled = false;
      runBtn.textContent = t("workflows.run");
    }
    renderInspector();
    applyRunHighlights(lastResult);
  }

  async function deleteActive() {
    if (!activeName) return;
    if (!window.confirm(t("workflows.deleteConfirm"))) return;
    await window.SecretaryAPI.request(
      "DELETE",
      `/api/workflows/${encodeURIComponent(activeName)}`
    );
    activeName = "";
    activeDef = null;
    lastResult = null;
    destroyEditor();
    await refreshList();
  }

  async function createFromTemplate() {
    let templates = [];
    try {
      const data = await window.SecretaryAPI.request("GET", "/api/workflows/templates");
      templates = Array.isArray(data?.templates) ? data.templates : [];
    } catch (error) {
      window.alert(error.message || String(error));
      return;
    }
    if (!templates.length) {
      window.alert(t("workflows.noTemplates"));
      return;
    }
    const labels = templates
      .map((item, index) => `${index + 1}. ${item.name} (${item.id}, ${item.node_count} nodes)`)
      .join("\n");
    const choice = window.prompt(`${t("workflows.pickTemplate")}\n${labels}`, "1");
    if (!choice) return;
    const index = Number(choice) - 1;
    const picked = templates[index];
    if (!picked) return;
    const name =
      window.prompt(t("workflows.templateName"), `${picked.id}_${Date.now().toString(36).slice(-4)}`) ||
      "";
    if (!name.trim()) return;
    try {
      const created = await window.SecretaryAPI.request(
        "POST",
        `/api/workflows/templates/${encodeURIComponent(picked.id)}`,
        { name: name.trim() },
      );
      activeName = created?.name || name.trim();
      lastResult = null;
      await refreshList();
    } catch (error) {
      window.alert(error.message || String(error));
    }
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
          config: {
            prompt_template: "用三条要点介绍：{{topic}}",
            _canvas: { x: 80, y: 140 },
          },
          inputs_schema: {},
          outputs_schema: { summary: "string" },
          on_failure: "stop",
        },
        {
          id: "summary",
          kind: "agent",
          config: {
            prompt_template: "把下面内容压成一句话：{{draft.summary}}",
            _canvas: { x: 360, y: 140 },
          },
          inputs_schema: {},
          outputs_schema: { summary: "string" },
          on_failure: "stop",
        },
      ],
      edges: [{ from: "draft", to: "summary", port: "default" }],
    };
    await window.SecretaryAPI.request(
      "PUT",
      `/api/workflows/${encodeURIComponent(name)}`,
      payload
    );
    activeName = name;
    lastResult = null;
    await refreshList();
  }

  window.WorkflowsModule = { open: openWorkflows, close: closeWorkflows };
})();
