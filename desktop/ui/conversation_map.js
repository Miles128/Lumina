(function () {
  "use strict";

  const mapViewEl = document.getElementById("conversation-map-view");
  if (!mapViewEl) return;

  const SVG_NS = "http://www.w3.org/2000/svg";
  const NODE_H = 62;
  const PAD = 22;
  const LAYOUT_X_STEP = 218;
  const LAYOUT_Y_STEP = 94;
  const LAYOUT_Y_OFFSET = 16;
  const ACCENT_BAR_W = 4;
  const TEXT_LEFT = 28;
  const TEXT_RIGHT_PAD = 12;
  const Q_BASELINE = 23;
  const A_BASELINE = 47;
  const DIVIDER_Y = 32;

  let currentThread = "";
  let treeData = null;
  let isOpen = false;
  let currentNodeWidth = 144;

  // ---- Text width estimation & truncation ----
  // SVG <text> doesn't clip automatically, so we estimate rendered width
  // (accounting for CJK vs ASCII) and truncate with ellipsis to prevent
  // text from overflowing the node card.
  function estimateTextWidth(text, fontSize) {
    let w = 0;
    for (const ch of String(text)) {
      if (/[\u3000-\u9fff\uff00-\uffef\u4e00-\u9fff]/.test(ch)) {
        w += fontSize; // CJK / full-width ≈ 1em
      } else if ("ilI' ".indexOf(ch) >= 0) {
        w += fontSize * 0.3;
      } else if ("mwMW@".indexOf(ch) >= 0) {
        w += fontSize * 0.8;
      } else {
        w += fontSize * 0.55;
      }
    }
    return w;
  }

  function truncateToWidth(text, maxWidth, fontSize) {
    const cleaned = String(text || "").replace(/\s+/g, " ").trim();
    if (!cleaned) return "";
    if (estimateTextWidth(cleaned, fontSize) <= maxWidth) return cleaned;
    // Binary search for the longest prefix + "…" that fits.
    let lo = 0;
    let hi = cleaned.length;
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      if (estimateTextWidth(cleaned.slice(0, mid) + "…", fontSize) <= maxWidth) {
        lo = mid;
      } else {
        hi = mid - 1;
      }
    }
    return lo > 0 ? cleaned.slice(0, lo) + "…" : "";
  }

  function t(key, vars) {
    return window.LuminaI18n ? window.LuminaI18n.t(key, vars) : key;
  }

  // Layout: root at top center, children of each node are centered
  // horizontally beneath their parent. Uses DFS post-order subtree width
  // computation, then pre-order placement — classic tidy tree layout.
  function computeLayout(nodes, rootId, containerWidth) {
    const byId = new Map();
    for (const n of nodes) byId.set(n.id, n);

    const childrenMap = new Map();
    for (const n of nodes) {
      const pid = n.parent_id || "";
      if (!childrenMap.has(pid)) childrenMap.set(pid, []);
      childrenMap.get(pid).push(n);
    }

    const NODE_W = Math.max(168, Math.floor((containerWidth || 600) * 0.26));

    // Build tree structure
    const treeNodes = new Map();
    for (const n of nodes) {
      treeNodes.set(n.id, { id: n.id, children: [], subtreeWidth: 0, x: 0, y: 0, virtual: false });
    }
    for (const n of nodes) {
      const pid = n.parent_id || "";
      if (pid && treeNodes.has(pid)) {
        treeNodes.get(pid).children.push(treeNodes.get(n.id));
      }
    }

    // Find ALL roots (nodes with no parent, or parent not in tree).
    // A thread can have multiple disconnected chains when the user starts
    // fresh topics within the same thread — each chain is a separate root.
    const roots = [];
    for (const n of nodes) {
      const pid = n.parent_id || "";
      if (!pid || !treeNodes.has(pid)) {
        roots.push(treeNodes.get(n.id));
      }
    }

    // Unify multiple roots under a virtual super-root so the existing
    // tidy-tree layout handles them as sibling subtrees (side by side).
    let rootNode = null;
    let isVirtualRoot = false;
    if (roots.length === 1) {
      rootNode = roots[0];
    } else if (roots.length > 1) {
      rootNode = {
        id: "__virtual_root__",
        children: roots,
        subtreeWidth: 0,
        x: 0,
        y: 0,
        virtual: true,
      };
      isVirtualRoot = true;
    } else if (nodes.length > 0) {
      rootNode = treeNodes.get(nodes[0].id);
    }

    // Post-order: compute subtree widths
    function computeSubtreeWidth(node) {
      if (!node) return 0;
      if (node.children.length === 0) {
        node.subtreeWidth = NODE_W;
        return NODE_W;
      }
      let total = 0;
      for (let i = 0; i < node.children.length; i++) {
        if (i > 0) total += PAD;
        total += computeSubtreeWidth(node.children[i]);
      }
      node.subtreeWidth = Math.max(NODE_W, total);
      return node.subtreeWidth;
    }

    if (rootNode) computeSubtreeWidth(rootNode);

    // Pre-order: assign positions.
    // Virtual root sits at depth -1 so real roots are at depth 0.
    const positions = new Map();
    function assignPositions(node, depth, leftX) {
      if (!node) return;
      if (!node.virtual) {
        node.y = depth * LAYOUT_Y_STEP + LAYOUT_Y_OFFSET;
      }
      if (node.children.length === 0) {
        if (!node.virtual) node.x = leftX;
      } else {
        let childLeft = leftX;
        for (const child of node.children) {
          assignPositions(child, depth + 1, childLeft);
          childLeft += child.subtreeWidth + PAD;
        }
        if (!node.virtual) {
          const firstChild = node.children[0];
          const lastChild = node.children[node.children.length - 1];
          const childrenCenter = (firstChild.x + lastChild.x + NODE_W) / 2;
          node.x = childrenCenter - NODE_W / 2;
        }
      }
      if (!node.virtual) {
        positions.set(node.id, { x: node.x, y: node.y });
      }
    }

    if (rootNode) assignPositions(rootNode, isVirtualRoot ? -1 : 0, PAD);

    // Compute bounds
    let maxX = 0;
    let minX = Infinity;
    let maxY = 0;
    for (const [, pos] of positions) {
      if (pos.x < minX) minX = pos.x;
      if (pos.x > maxX) maxX = pos.x;
      if (pos.y > maxY) maxY = pos.y;
    }
    if (minX === Infinity) minX = 0;

    // Ensure no negative x
    if (minX < 0) {
      const shift = -minX + PAD;
      for (const [id, pos] of positions) {
        positions.set(id, { x: pos.x + shift, y: pos.y });
      }
      maxX += shift;
    }

    const width = maxX + NODE_W + PAD;
    return { positions, maxWidth: width, nodeWidth: NODE_W };
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

  function userPreview(node, maxWidth, fontSize) {
    const text = truncateToWidth(node.user_preview, maxWidth, fontSize);
    return text || "(提问)";
  }

  function assistantPreview(node, maxWidth, fontSize) {
    if (!node.has_assistant) return "（待回答）";
    const text = truncateToWidth(node.assistant_preview, maxWidth, fontSize);
    return text || "(灵犀)";
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

  // Live update: accept pre-fetched tree data (from chat.js fetchTreeData)
  // and re-render if the map is currently open. Avoids a second HTTP request
  // and keeps the map in sync as new messages arrive.
  function update(treeDataPayload) {
    if (!isOpen) return;
    if (!treeDataPayload || !Array.isArray(treeDataPayload.nodes)) return;
    // Only update if the thread matches what's currently displayed.
    if (currentThread && treeDataPayload._threadId && treeDataPayload._threadId !== currentThread) {
      return;
    }
    treeData = treeDataPayload;
    render();
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
      showStatus(t("map.empty"));
      return;
    }

    const nodes = treeData.nodes;
    const rootId = treeData.root_id || (nodes[0] && nodes[0].id) || "";
    const activeLeafId = treeData.active_leaf_id || "";
    const containerWidth = mapViewEl.clientWidth || 600;
    const layout = computeLayout(nodes, rootId, containerWidth);
    const positions = layout.positions;
    const nodeWidth = layout.nodeWidth;
    currentNodeWidth = nodeWidth;
    const activeSet = computeActivePathSet(nodes, activeLeafId);
    const textAvailWidth = nodeWidth - TEXT_LEFT - TEXT_RIGHT_PAD;

    let maxY = 0;
    for (const [, pos] of positions) {
      if (pos.y > maxY) maxY = pos.y;
    }
    const width = layout.maxWidth;
    const height = maxY + NODE_H + PAD * 2;

    // Count children per node (for branch-point indicators + header stats)
    const childrenCount = new Map();
    for (const node of nodes) {
      const pid = node.parent_id || "";
      childrenCount.set(pid, (childrenCount.get(pid) || 0) + 1);
    }
    const branchCount = [...childrenCount.values()].filter((c) => c > 1).length;
    let maxDepth = 0;
    for (const [, pos] of positions) {
      const d = Math.round(pos.y / LAYOUT_Y_STEP) + 1;
      if (d > maxDepth) maxDepth = d;
    }

    const header = document.createElement("div");
    header.className = "map-header";
    const title = document.createElement("span");
    title.className = "map-title";
    title.textContent = t("map.title");
    const stats = document.createElement("span");
    stats.className = "map-stats";
    stats.textContent = `${nodes.length} 轮 · ${branchCount} 分支 · ${maxDepth} 层`;
    const hint = document.createElement("span");
    hint.className = "map-hint";
    hint.textContent = t("map.hint");
    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "map-close";
    closeBtn.textContent = "×";
    closeBtn.setAttribute("aria-label", "关闭地图");
    closeBtn.addEventListener("click", close);
    header.appendChild(title);
    header.appendChild(stats);
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

    // SVG defs: dot-grid pattern for the canvas background
    const defs = document.createElementNS(SVG_NS, "defs");
    const dotPattern = document.createElementNS(SVG_NS, "pattern");
    dotPattern.setAttribute("id", "map-dotgrid");
    dotPattern.setAttribute("width", "22");
    dotPattern.setAttribute("height", "22");
    dotPattern.setAttribute("patternUnits", "userSpaceOnUse");
    const gridDot = document.createElementNS(SVG_NS, "circle");
    gridDot.setAttribute("cx", "1");
    gridDot.setAttribute("cy", "1");
    gridDot.setAttribute("r", "0.8");
    gridDot.setAttribute("class", "map-grid-dot");
    dotPattern.appendChild(gridDot);
    defs.appendChild(dotPattern);
    svg.appendChild(defs);

    // Background with dot grid
    const bgRect = document.createElementNS(SVG_NS, "rect");
    bgRect.setAttribute("width", String(width));
    bgRect.setAttribute("height", String(height));
    bgRect.setAttribute("fill", "url(#map-dotgrid)");
    svg.appendChild(bgRect);

    const byId = new Map();
    for (const n of nodes) byId.set(n.id, n);

    // Edges (drawn before nodes so nodes paint over them)
    // Orthogonal routing: parent bottom-center → down → horizontal → child top-center
    for (const node of nodes) {
      const pid = node.parent_id || "";
      if (!pid || !byId.has(pid)) continue;
      const from = positions.get(pid);
      const to = positions.get(node.id);
      if (!from || !to) continue;
      const isActive = activeSet.has(node.id) && activeSet.has(pid);
      const x1 = from.x + nodeWidth / 2 + PAD;
      const y1 = from.y + NODE_H + PAD;
      const x2 = to.x + nodeWidth / 2 + PAD;
      const y2 = to.y + PAD;
      const midY = (y1 + y2) / 2;
      const r = 8;
      let d;
      if (Math.abs(x2 - x1) < 1) {
        d = `M ${x1} ${y1} L ${x2} ${y2}`;
      } else {
        const dir = x2 > x1 ? 1 : -1;
        d =
          `M ${x1} ${y1} ` +
          `L ${x1} ${midY - r} ` +
          `Q ${x1} ${midY} ${x1 + dir * r} ${midY} ` +
          `L ${x2 - dir * r} ${midY} ` +
          `Q ${x2} ${midY} ${x2} ${midY + r} ` +
          `L ${x2} ${y2}`;
      }
      // Active path glow: wide, semi-transparent highlight behind the edge
      if (isActive) {
        const glow = document.createElementNS(SVG_NS, "path");
        glow.setAttribute("d", d);
        glow.setAttribute("class", "map-edge-glow");
        svg.appendChild(glow);
      }
      const line = document.createElementNS(SVG_NS, "path");
      line.setAttribute("d", d);
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
      const hasBranch = (childrenCount.get(node.id) || 0) > 1;
      const g = document.createElementNS(SVG_NS, "g");
      g.setAttribute(
        "class",
        `map-node${isActive ? " is-active" : ""}${isArchived ? " is-archived" : ""}${isLeaf ? " is-leaf" : ""}${hasBranch ? " is-branch" : ""}`,
      );
      g.setAttribute("transform", `translate(${pos.x + PAD}, ${pos.y + PAD})`);
      g.dataset.nodeId = node.id;
      const depth = Math.round(pos.y / LAYOUT_Y_STEP);
      g.style.animationDelay = `${Math.min(depth * 0.02, 0.2)}s`;

      // Left accent bar (state indicator)
      const accentBar = document.createElementNS(SVG_NS, "rect");
      accentBar.setAttribute("class", "map-node-accent");
      accentBar.setAttribute("width", String(ACCENT_BAR_W));
      accentBar.setAttribute("height", String(NODE_H));
      accentBar.setAttribute("rx", "2");
      g.appendChild(accentBar);

      // Card body
      const rect = document.createElementNS(SVG_NS, "rect");
      rect.setAttribute("class", "map-node-body");
      rect.setAttribute("width", String(nodeWidth));
      rect.setAttribute("height", String(NODE_H));
      rect.setAttribute("rx", "8");
      g.appendChild(rect);

      // Divider between Q and A rows
      const divider = document.createElementNS(SVG_NS, "line");
      divider.setAttribute("class", "map-node-divider");
      divider.setAttribute("x1", String(ACCENT_BAR_W + 6));
      divider.setAttribute("y1", String(DIVIDER_Y));
      divider.setAttribute("x2", String(nodeWidth - 8));
      divider.setAttribute("y2", String(DIVIDER_Y));
      g.appendChild(divider);

      // Q label
      const qLabel = document.createElementNS(SVG_NS, "text");
      qLabel.setAttribute("class", "map-node-q-label");
      qLabel.setAttribute("x", String(ACCENT_BAR_W + 8));
      qLabel.setAttribute("y", String(Q_BASELINE));
      qLabel.textContent = "问";
      g.appendChild(qLabel);

      // Q preview text
      const qText = document.createElementNS(SVG_NS, "text");
      qText.setAttribute("class", "map-node-q-text");
      qText.setAttribute("x", String(TEXT_LEFT));
      qText.setAttribute("y", String(Q_BASELINE));
      qText.textContent = userPreview(node, textAvailWidth, 11);
      g.appendChild(qText);

      // A label
      const aLabel = document.createElementNS(SVG_NS, "text");
      aLabel.setAttribute("class", "map-node-a-label");
      aLabel.setAttribute("x", String(ACCENT_BAR_W + 8));
      aLabel.setAttribute("y", String(A_BASELINE));
      aLabel.textContent = "答";
      g.appendChild(aLabel);

      // A preview text
      const aText = document.createElementNS(SVG_NS, "text");
      aText.setAttribute("class", "map-node-a-text");
      aText.setAttribute("x", String(TEXT_LEFT));
      aText.setAttribute("y", String(A_BASELINE));
      aText.textContent = assistantPreview(node, textAvailWidth, 11);
      g.appendChild(aText);

      // Leaf badge (current position indicator)
      if (isLeaf) {
        const badge = document.createElementNS(SVG_NS, "circle");
        badge.setAttribute("class", "map-node-badge");
        badge.setAttribute("cx", String(nodeWidth - 10));
        badge.setAttribute("cy", "10");
        badge.setAttribute("r", "4");
        g.appendChild(badge);
      }

      // Branch-point indicator (nodes with multiple children)
      if (hasBranch) {
        const branchDot = document.createElementNS(SVG_NS, "circle");
        branchDot.setAttribute("class", "map-node-branch-dot");
        branchDot.setAttribute("cx", String(nodeWidth - 10));
        branchDot.setAttribute("cy", String(NODE_H - 10));
        branchDot.setAttribute("r", "2.5");
        g.appendChild(branchDot);
      }

      g.addEventListener("click", () => {
        void onNodeClick(node);
      });
      g.addEventListener("mouseenter", () => showNodeTooltip(node, g));
      g.addEventListener("mouseleave", hideNodeTooltip);

      svg.appendChild(g);
    }

    scrollWrap.appendChild(svg);
    mapViewEl.appendChild(scrollWrap);
    // Tooltip container is appended once to the map view (HTML overlay).
    ensureTooltipEl();
  }

  // ---- Rich HTML hover tooltip ----

  let tooltipEl = null;

  function ensureTooltipEl() {
    if (tooltipEl && tooltipEl.isConnected) return tooltipEl;
    tooltipEl = document.createElement("div");
    tooltipEl.className = "map-tooltip";
    tooltipEl.hidden = true;
    mapViewEl.appendChild(tooltipEl);
    return tooltipEl;
  }

  function showNodeTooltip(node, svgGroup) {
    const el = ensureTooltipEl();
    const q = String(node.user_preview || "").trim() || "(提问)";
    const a = node.has_assistant
      ? String(node.assistant_preview || "").trim() || "(灵犀)"
      : "（待回答）";
    el.innerHTML =
      `<div class="map-tooltip-row"><span class="map-tooltip-label">问</span>` +
      `<span class="map-tooltip-text"></span></div>` +
      `<div class="map-tooltip-row"><span class="map-tooltip-label">答</span>` +
      `<span class="map-tooltip-text"></span></div>`;
    el.querySelectorAll(".map-tooltip-text")[0].textContent = q;
    el.querySelectorAll(".map-tooltip-text")[1].textContent = a;
    el.hidden = false;
    positionTooltip(el, svgGroup);
  }

  function positionTooltip(el, svgGroup) {
    const wrapBox = mapViewEl.getBoundingClientRect();
    const groupBox = svgGroup.getBoundingClientRect();
    // Prefer placing the tooltip to the right of the node; fall back to left.
    const tooltipBox = el.getBoundingClientRect();
    let left = groupBox.right - wrapBox.left + 8;
    let top = groupBox.top - wrapBox.top + groupBox.height / 2 - tooltipBox.height / 2;
    if (left + tooltipBox.width > wrapBox.width - 8) {
      left = groupBox.left - wrapBox.left - tooltipBox.width - 8;
    }
    if (top < 8) top = 8;
    if (top + tooltipBox.height > wrapBox.height - 8) {
      top = wrapBox.height - tooltipBox.height - 8;
    }
    el.style.left = `${Math.max(8, left)}px`;
    el.style.top = `${top}px`;
  }

  function hideNodeTooltip() {
    if (tooltipEl) tooltipEl.hidden = true;
  }

  // Guard against concurrent branch switches: rapid clicks on different nodes
  // would fire overlapping PUT requests and leave the map in an inconsistent
  // state. isSwitching is set on entry and cleared in finally.
  let isSwitching = false;

  async function onNodeClick(node) {
    if (isSwitching) return;
    if (!currentThread || !node || !node.id) return;
    if (node.archived) return;
    if (node.id === (treeData && treeData.active_leaf_id)) return;
    isSwitching = true;
    showStatus(t("map.switching"));
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
      showStatus(t("map.switchFailed", { error: error.message || t("map.retry") }));
    } finally {
      isSwitching = false;
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
    // Scroll the active leaf node into view after the DOM settles.
    requestAnimationFrame(() => scrollToActiveNode());
  }

  // Scroll the active leaf node into the center of the map scroll area.
  function scrollToActiveNode() {
    if (!treeData || !treeData.active_leaf_id) return;
    const node = mapViewEl.querySelector(
      `.map-node[data-node-id="${CSS.escape(treeData.active_leaf_id)}"]`,
    );
    if (!node) return;
    const scrollWrap = mapViewEl.querySelector(".map-scroll");
    if (!scrollWrap) return;
    // The node's x/y position in SVG coords is encoded in its transform attr.
    const transform = node.getAttribute("transform") || "";
    const match = transform.match(/translate\(([-\d.]+),\s*([-\d.]+)\)/);
    if (!match) return;
    const nodeX = parseFloat(match[1]);
    const nodeY = parseFloat(match[2]);
    const wrapBox = scrollWrap.getBoundingClientRect();
    const targetScrollLeft = Math.max(0, nodeX - wrapBox.width / 2 + currentNodeWidth / 2);
    const targetScrollTop = Math.max(0, nodeY - wrapBox.height / 2 + NODE_H / 2);
    scrollWrap.scrollTo({ left: targetScrollLeft, top: targetScrollTop, behavior: "smooth" });
  }

  // Highlight a node temporarily (e.g. when its message is hovered in chat).
  function highlightNode(nodeId) {
    if (!isOpen || !nodeId) return;
    // Clear previous highlight.
    mapViewEl.querySelectorAll(".map-node.is-highlighted").forEach((el) => {
      el.classList.remove("is-highlighted");
    });
    const node = mapViewEl.querySelector(
      `.map-node[data-node-id="${CSS.escape(nodeId)}"]`,
    );
    if (node) node.classList.add("is-highlighted");
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
    // Live update from chat.js (avoids re-fetching).
    update(treeDataPayload) {
      update(treeDataPayload);
    },
    // Highlight a node (e.g. when its message is hovered in the chat list).
    highlightNode(nodeId) {
      highlightNode(nodeId);
    },
  };
})();
