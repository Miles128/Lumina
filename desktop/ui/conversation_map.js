(function () {
  "use strict";

  const mapViewEl = document.getElementById("conversation-map-view");
  if (!mapViewEl) return;

  const SVG_NS = "http://www.w3.org/2000/svg";
  // Width +50% vs previous 144; taller card for up to 3 text lines.
  const NODE_W = 216;
  const NODE_H = 80;
  const PAD = 20;
  const LAYOUT_X_GAP = 28;
  const LAYOUT_Y_STEP = 108;
  const LAYOUT_Y_OFFSET = 8;
  const PREVIEW_CHARS = 42;
  const TEXT_MAX_LINES = 3;
  const TEXT_LINE_H = 12;

  let currentThread = "";
  let treeData = null;
  let isOpen = false;

  function t(key) {
    return window.LuminaI18n ? window.LuminaI18n.t(key) : key;
  }

  // Vertical spine (depth → y). Sibling forks fan out left–right (x).
  function computeLayout(nodes, rootId) {
    const byId = new Map();
    for (const n of nodes) byId.set(n.id, n);

    const childrenMap = new Map();
    for (const n of nodes) {
      const pid = n.parent_id || "";
      if (!childrenMap.has(pid)) childrenMap.set(pid, []);
      childrenMap.get(pid).push(n);
    }

    const positions = new Map();
    const subtreeWidth = new Map();

    function measure(id) {
      if (!id || !byId.has(id)) return NODE_W;
      const kids = (childrenMap.get(id) || []).filter((k) => byId.has(k.id));
      if (!kids.length) {
        subtreeWidth.set(id, NODE_W);
        return NODE_W;
      }
      let total = 0;
      for (const k of kids) {
        total += measure(k.id);
      }
      total += LAYOUT_X_GAP * (kids.length - 1);
      const w = Math.max(NODE_W, total);
      subtreeWidth.set(id, w);
      return w;
    }

    function place(id, depth, left) {
      if (!id || !byId.has(id) || positions.has(id)) return;
      const w = subtreeWidth.get(id) || NODE_W;
      const kids = (childrenMap.get(id) || []).filter((k) => byId.has(k.id));
      positions.set(id, {
        x: left + (w - NODE_W) / 2,
        y: depth * LAYOUT_Y_STEP + LAYOUT_Y_OFFSET,
      });
      if (!kids.length) return;
      let cursor = left;
      const kidsTotal =
        kids.reduce((sum, k) => sum + (subtreeWidth.get(k.id) || NODE_W), 0) +
        LAYOUT_X_GAP * (kids.length - 1);
      if (kidsTotal < w) {
        cursor += (w - kidsTotal) / 2;
      }
      for (const k of kids) {
        const kw = subtreeWidth.get(k.id) || NODE_W;
        place(k.id, depth + 1, cursor);
        cursor += kw + LAYOUT_X_GAP;
      }
    }

    const roots = [];
    if (rootId && byId.has(rootId)) {
      roots.push(rootId);
    } else {
      for (const n of nodes) {
        if (!n.parent_id || !byId.has(n.parent_id)) roots.push(n.id);
      }
    }

    let forestLeft = 0;
    for (const rid of roots) {
      const w = measure(rid);
      place(rid, 0, forestLeft);
      forestLeft += w + LAYOUT_X_GAP;
    }

    // Orphans not reached (cycles / broken links)
    for (const n of nodes) {
      if (!positions.has(n.id)) {
        measure(n.id);
        place(n.id, 0, forestLeft);
        forestLeft += (subtreeWidth.get(n.id) || NODE_W) + LAYOUT_X_GAP;
      }
    }

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
    return text.length > PREVIEW_CHARS ? `${text.slice(0, PREVIEW_CHARS)}…` : text;
  }

  function wrapPreviewLines(raw, maxLines = TEXT_MAX_LINES) {
    const text = truncatePreview(raw);
    if (!text) return [];
    const lines = [];
    // ~10px font in ~190px content width ≈ 18 CJK chars / line
    const perLine = 18;
    let rest = text;
    while (rest && lines.length < maxLines) {
      if (lines.length === maxLines - 1) {
        // 最后一行：超长则截断加省略号
        lines.push(rest.length > perLine ? `${rest.slice(0, perLine - 1)}…` : rest);
        break;
      }
      if (rest.length <= perLine) {
        lines.push(rest);
        break;
      }
      lines.push(rest.slice(0, perLine));
      rest = rest.slice(perLine);
    }
    return lines;
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

  function appendMultilineText(g, className, x, y, lines) {
    const textEl = document.createElementNS(SVG_NS, "text");
    textEl.setAttribute("class", className);
    textEl.setAttribute("x", String(x));
    textEl.setAttribute("y", String(y));
    lines.forEach((line, index) => {
      const tspan = document.createElementNS(SVG_NS, "tspan");
      tspan.setAttribute("x", String(x));
      if (index === 0) {
        tspan.setAttribute("y", String(y));
      } else {
        tspan.setAttribute("dy", String(TEXT_LINE_H));
      }
      tspan.textContent = line;
      textEl.appendChild(tspan);
    });
    g.appendChild(textEl);
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

    // Edges: parent bottom → child top (vertical tree)
    for (const node of nodes) {
      const pid = node.parent_id || "";
      if (!pid || !byId.has(pid)) continue;
      const from = positions.get(pid);
      const to = positions.get(node.id);
      if (!from || !to) continue;
      const isActive = activeSet.has(node.id) && activeSet.has(pid);
      const line = document.createElementNS(SVG_NS, "path");
      const x1 = from.x + NODE_W / 2 + PAD;
      const y1 = from.y + NODE_H + PAD;
      const x2 = to.x + NODE_W / 2 + PAD;
      const y2 = to.y + PAD;
      const midY = (y1 + y2) / 2;
      line.setAttribute(
        "d",
        `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`,
      );
      line.setAttribute("class", `map-edge${isActive ? " is-active" : ""}`);
      svg.appendChild(line);
    }

    for (const node of nodes) {
      const pos = positions.get(node.id);
      if (!pos) continue;
      const isActive = activeSet.has(node.id) || Boolean(node.active);
      const isArchived = Boolean(node.archived);
      const isLeaf = node.id === activeLeafId;
      // done: 在活跃路径上且非叶子（已完成的祖先节点）
      const isDone = activeSet.has(node.id) && !isLeaf;
      // branch: 不在活跃路径上的非叶子节点
      const isBranch = !activeSet.has(node.id) && !isLeaf;
      const g = document.createElementNS(SVG_NS, "g");
      g.setAttribute(
        "class",
        `map-node${isActive ? " is-active" : ""}${isArchived ? " is-archived" : ""}${isLeaf ? " is-leaf" : ""}${isDone ? " is-done" : ""}${isBranch ? " is-branch" : ""}`,
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
      qLabel.setAttribute("y", "14");
      qLabel.textContent = "问";
      g.appendChild(qLabel);

      const qLines = wrapPreviewLines(node.user_preview || "(提问)", 2);
      appendMultilineText(g, "map-node-q-text", 22, 14, qLines.length ? qLines : ["(提问)"]);

      const aLabel = document.createElementNS(SVG_NS, "text");
      aLabel.setAttribute("class", "map-node-a-label");
      aLabel.setAttribute("x", "8");
      aLabel.setAttribute("y", "58");
      aLabel.textContent = "答";
      g.appendChild(aLabel);

      const aLines = wrapPreviewLines(
        node.has_assistant ? node.assistant_preview || "(灵犀)" : "（待回答）",
        1,
      );
      appendMultilineText(
        g,
        "map-node-a-text",
        22,
        58,
        aLines.length ? aLines : [node.has_assistant ? "(灵犀)" : "（待回答）"],
      );

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

  let toggleBound = false;

  function bindToggleButton() {
    if (toggleBound) return;
    toggleBound = true;
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

  // Self-init so a missing/blocked bootstrap call cannot silently disable the map button.
  bindToggleButton();
})();
