(function () {
  "use strict";

  const mapViewEl = document.getElementById("conversation-map-view");
  if (!mapViewEl) return;

  const SVG_NS = "http://www.w3.org/2000/svg";
  const NODE_W = 144;
  const NODE_H = 38;
  const PAD = 16;
  const LAYOUT_X_STEP = 168;
  const LAYOUT_X_OFFSET = 12;
  const LAYOUT_Y_STEP = 52;
  const LAYOUT_Y_OFFSET = 12;
  const PREVIEW_LEN = 14;

  let currentThread = "";
  let treeData = null;
  let isOpen = false;

  function t(key) {
    return window.LuminaI18n ? window.LuminaI18n.t(key) : key;
  }

  // BFS from root: each depth level gets a fixed x, nodes within a level
  // are stacked vertically by discovery order. Simple grid layout.
  function computeLayout(nodes, rootId) {
    const byId = new Map();
    for (const n of nodes) byId.set(n.id, n);

    const childrenMap = new Map();
    for (const n of nodes) {
      const pid = n.parent_id || "";
      if (!childrenMap.has(pid)) childrenMap.set(pid, []);
      childrenMap.get(pid).push(n);
    }

    const levels = [];
    const visited = new Set();
    const queue = [{ id: rootId, depth: 0 }];
    while (queue.length) {
      const { id, depth } = queue.shift();
      if (!id || visited.has(id) || !byId.has(id)) continue;
      visited.add(id);
      if (!levels[depth]) levels[depth] = [];
      levels[depth].push(id);
      const kids = childrenMap.get(id) || [];
      for (const k of kids) {
        if (!visited.has(k.id)) queue.push({ id: k.id, depth: depth + 1 });
      }
    }

    // Append any unreachable orphans at depth 0 so they still render.
    for (const n of nodes) {
      if (!visited.has(n.id)) {
        if (!levels[0]) levels[0] = [];
        levels[0].push(n.id);
      }
    }

    const positions = new Map();
    levels.forEach((ids, depth) => {
      ids.forEach((id, index) => {
        positions.set(id, {
          x: depth * LAYOUT_X_STEP + LAYOUT_X_OFFSET,
          y: index * LAYOUT_Y_STEP + LAYOUT_Y_OFFSET,
        });
      });
    });
    return positions;
  }

  function computeActivePathSet(nodes, activeLeafId) {
    const set = new Set();
    if (!activeLeafId) return set;
    const byId = new Map();
    for (const n of nodes) byId.set(n.id, n);
    let cur = activeLeafId;
    let guard = 0;
    while (cur && byId.has(cur) && !set.has(cur) && guard < 1000) {
      set.add(cur);
      cur = byId.get(cur).parent_id || "";
      guard += 1;
    }
    return set;
  }

  function truncatePreview(raw) {
    const text = String(raw || "").replace(/\s+/g, " ").trim();
    if (!text) return "";
    return text.length > PREVIEW_LEN ? `${text.slice(0, PREVIEW_LEN)}…` : text;
  }

  function userPreview(node) {
    return truncatePreview(node.user_preview) || "(提问)";
  }

  function assistantPreview(node) {
    if (!node.has_assistant) return "（待回答）";
    return truncatePreview(node.assistant_preview) || "(灵犀)";
  }

  async function loadTree(threadId) {
    if (!threadId) {
      treeData = null;
      return;
    }
    try {
      treeData = await window.SecretaryAPI.request(
        "GET",
        `/api/chat/threads/${encodeURIComponent(threadId)}/tree`,
        null,
        { timeoutMs: 8000 },
      );
    } catch (_error) {
      treeData = null;
    }
  }

  function clearView() {
    mapViewEl.innerHTML = "";
  }

  function showStatus(message) {
    clearView();
    const el = document.createElement("div");
    el.className = "map-status";
    el.textContent = message;
    mapViewEl.appendChild(el);
  }

  function render() {
    if (!mapViewEl) return;
    clearView();

    if (!treeData || !Array.isArray(treeData.nodes) || !treeData.nodes.length) {
      showStatus("暂无对话节点");
      return;
    }

    const nodes = treeData.nodes;
    const rootId = treeData.root_id || (nodes[0] && nodes[0].id) || "";
    const activeLeafId = treeData.active_leaf_id || "";
    const positions = computeLayout(nodes, rootId);
    const activeSet = computeActivePathSet(nodes, activeLeafId);

    let maxX = 0;
    let maxY = 0;
    for (const [, pos] of positions) {
      if (pos.x > maxX) maxX = pos.x;
      if (pos.y > maxY) maxY = pos.y;
    }
    const width = maxX + NODE_W + PAD * 2;
    const height = maxY + NODE_H + PAD * 2;

    const header = document.createElement("div");
    header.className = "map-header";
    const title = document.createElement("span");
    title.className = "map-title";
    title.textContent = "对话地图";
    const hint = document.createElement("span");
    hint.className = "map-hint";
    hint.textContent = "点击节点切换分支";
    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "map-close";
    closeBtn.textContent = "×";
    closeBtn.setAttribute("aria-label", "关闭地图");
    closeBtn.addEventListener("click", close);
    header.appendChild(title);
    header.appendChild(hint);
    header.appendChild(closeBtn);
    mapViewEl.appendChild(header);

    const scrollWrap = document.createElement("div");
    scrollWrap.className = "map-scroll";

    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "map-svg");
    svg.setAttribute("width", String(width));
    svg.setAttribute("height", String(height));
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

    const byId = new Map();
    for (const n of nodes) byId.set(n.id, n);

    // Edges first (so nodes paint over them)
    for (const node of nodes) {
      const pid = node.parent_id || "";
      if (!pid || !byId.has(pid)) continue;
      const from = positions.get(pid);
      const to = positions.get(node.id);
      if (!from || !to) continue;
      const isActive = activeSet.has(node.id) && activeSet.has(pid);
      const line = document.createElementNS(SVG_NS, "path");
      const x1 = from.x + NODE_W + PAD;
      const y1 = from.y + NODE_H / 2 + PAD;
      const x2 = to.x + PAD;
      const y2 = to.y + NODE_H / 2 + PAD;
      const midX = (x1 + x2) / 2;
      line.setAttribute(
        "d",
        `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`,
      );
      line.setAttribute("class", `map-edge${isActive ? " is-active" : ""}`);
      svg.appendChild(line);
    }

    // Nodes (each node = one Q&A turn)
    for (const node of nodes) {
      const pos = positions.get(node.id);
      if (!pos) continue;
      const isActive = activeSet.has(node.id) || Boolean(node.active);
      const isArchived = Boolean(node.archived);
      const isLeaf = node.id === activeLeafId;
      const g = document.createElementNS(SVG_NS, "g");
      g.setAttribute(
        "class",
        `map-node${isActive ? " is-active" : ""}${isArchived ? " is-archived" : ""}${isLeaf ? " is-leaf" : ""}`,
      );
      g.setAttribute("transform", `translate(${pos.x + PAD}, ${pos.y + PAD})`);
      g.dataset.nodeId = node.id;

      const rect = document.createElementNS(SVG_NS, "rect");
      rect.setAttribute("width", String(NODE_W));
      rect.setAttribute("height", String(NODE_H));
      rect.setAttribute("rx", "6");
      g.appendChild(rect);

      const qLabel = document.createElementNS(SVG_NS, "text");
      qLabel.setAttribute("class", "map-node-q-label");
      qLabel.setAttribute("x", "8");
      qLabel.setAttribute("y", "15");
      qLabel.textContent = "问";
      g.appendChild(qLabel);

      const qText = document.createElementNS(SVG_NS, "text");
      qText.setAttribute("class", "map-node-q-text");
      qText.setAttribute("x", "22");
      qText.setAttribute("y", "15");
      qText.textContent = userPreview(node);
      g.appendChild(qText);

      const aLabel = document.createElementNS(SVG_NS, "text");
      aLabel.setAttribute("class", "map-node-a-label");
      aLabel.setAttribute("x", "8");
      aLabel.setAttribute("y", "29");
      aLabel.textContent = "答";
      g.appendChild(aLabel);

      const aText = document.createElementNS(SVG_NS, "text");
      aText.setAttribute("class", "map-node-a-text");
      aText.setAttribute("x", "22");
      aText.setAttribute("y", "29");
      aText.textContent = assistantPreview(node);
      g.appendChild(aText);

      const tooltip = document.createElementNS(SVG_NS, "title");
      tooltip.textContent = `问：${userPreview(node)}\n答：${assistantPreview(node)}`;
      g.appendChild(tooltip);

      if (isLeaf) {
        const badge = document.createElementNS(SVG_NS, "circle");
        badge.setAttribute("class", "map-node-badge");
        badge.setAttribute("cx", String(NODE_W - 8));
        badge.setAttribute("cy", "8");
        badge.setAttribute("r", "3");
        g.appendChild(badge);
      }

      g.addEventListener("click", () => {
        void onNodeClick(node);
      });

      svg.appendChild(g);
    }

    scrollWrap.appendChild(svg);
    mapViewEl.appendChild(scrollWrap);
  }

  async function onNodeClick(node) {
    if (!currentThread || !node || !node.id) return;
    if (node.archived) return;
    if (node.id === (treeData && treeData.active_leaf_id)) return;
    showStatus("正在切换分支…");
    try {
      await window.SecretaryAPI.request(
        "PUT",
        `/api/chat/threads/${encodeURIComponent(currentThread)}/active-leaf`,
        { leaf_id: node.id },
        { timeoutMs: 8000 },
      );
      await loadTree(currentThread);
      render();
      document.dispatchEvent(
        new CustomEvent("conversation:active-leaf-changed", {
          detail: { thread_id: currentThread, leaf_id: node.id },
        }),
      );
    } catch (error) {
      showStatus(`切换失败: ${error.message || "请稍后重试"}`);
    }
  }

  function setBtnActive(active) {
    document.querySelectorAll(".js-map-toggle").forEach((btn) => {
      btn.classList.toggle("is-active", active);
    });
  }

  async function open(threadId) {
    if (!threadId) return;
    currentThread = threadId;
    isOpen = true;
    mapViewEl.hidden = false;
    document.body.classList.add("map-view-open");
    setBtnActive(true);
    showStatus(t("settings.loading") || "加载中…");
    await loadTree(threadId);
    render();
  }

  function close() {
    isOpen = false;
    mapViewEl.hidden = true;
    document.body.classList.remove("map-view-open");
    setBtnActive(false);
    clearView();
  }

  function toggle(threadId) {
    if (isOpen) {
      close();
    } else {
      void open(threadId);
    }
  }

  function bindToggleButton() {
    document.addEventListener("click", (event) => {
      const btn = event.target.closest(".js-map-toggle");
      if (!btn) return;
      const tid =
        (window.ChatModule && typeof window.ChatModule.getCurrentThreadId === "function" && window.ChatModule.getCurrentThreadId()) ||
        currentThread ||
        "";
      if (!tid) return;
      toggle(tid);
    });
  }

  window.ConversationMapModule = {
    init() {
      bindToggleButton();
    },
    open(threadId) {
      void open(threadId);
    },
    close,
    toggle(threadId) {
      toggle(threadId);
    },
    isOpen() {
      return isOpen;
    },
  };
})();
