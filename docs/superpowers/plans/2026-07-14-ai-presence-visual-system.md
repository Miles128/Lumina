# AI 在场视觉系统 · 实现计划（P0 + P1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Lumina 前端落地统一的「AI 在场」视觉系统——共享信号色（青 #06b6d4）+ 共享节奏语言，覆盖思考态光场呼吸、输出态信号条、对话地图升级三个落点。

**Architecture:** 纯前端改造，不动后端。新增共享设计 token 到 tokens.css，改造 chat.css 的 typing 区块与 bot 气泡，升级 conversation_map 的节点与边视觉。所有动画用 transform/opacity/background-position，遵守 prefers-reduced-motion。

**Tech Stack:** 原生 JS + CSS 变量 + SVG（对话地图已有）。无前端测试框架，采用「启动应用 + 目视验证清单」替代单测。后端测试（pytest/ruff/mypy）不受影响。

**Spec:** [docs/superpowers/specs/2026-07-14-ai-presence-visual-system-design.md](file:///Users/sihai/Documents/My%20Projects/Lumina/docs/superpowers/specs/2026-07-14-ai-presence-visual-system-design.md)

**范围说明：** 本计划覆盖 spec §4.1 / §4.2 / §4.3（P0 + P1）。§4.4 Skill 编排视图依赖后端 skill_flow 事件，留作独立计划。

---

## 文件结构

| 文件 | 职责 | 操作 |
|---|---|---|
| `desktop/ui/tokens.css` | 共享设计 token（信号色 / 网格 / 节奏） | 修改 |
| `desktop/ui/index.html` | typing 区块结构改造 + 资源版本号 | 修改 |
| `desktop/ui/chat.css` | typing 光场 + bot-sig 信号条 + 对话地图升级 | 修改 |
| `desktop/ui/chat.js` | beginStreamingBubble 插入 bot-sig 元素 | 修改 |
| `desktop/ui/i18n.js` | 新增 chat.thinking key | 修改 |
| `desktop/ui/conversation_map.js` | 节点状态 class 标注（done/active/branch） | 修改 |

---

## Task 1: 共享设计 Token

**Files:**
- Modify: `desktop/ui/tokens.css`（在 `:root` 块内追加，并在 `[data-theme="dark"]` / `[data-theme="paper"]` 块内追加覆盖）

- [ ] **Step 1: 在 `:root` 块追加信号色 + 网格 + 节奏变量**

打开 `desktop/ui/tokens.css`，定位到 `:root { ... }` 块（行 1–28）。在 `--bubble-user-bg: #f3f3f3;` 这一行之后、`color-scheme: light;` 之前追加：

```css
  /* AI 在场视觉系统 —— 共享 token */
  --sig: #06b6d4;
  --sig-soft: rgba(6, 182, 212, 0.35);
  --sig-faint: rgba(6, 182, 212, 0.12);
  --sig-glow: 0 0 12px var(--sig);
  --grid-size: 15px;
  --grid-line: rgba(0, 0, 0, 0.05);
  --pace-breathe: 2.4s;
  --pace-breathe-deep: 3.2s;
  --pace-flow: 1.2s;
  --pace-signal: 1.6s;
```

- [ ] **Step 2: 在 `[data-theme="dark"]` 块追加暗色覆盖**

定位到 `[data-theme="dark"] { ... }`（行 30–49）。在 `--bubble-user-bg: #1a1a1a;` 之后、`color-scheme: dark;` 之前追加：

```css
  --sig: #22d3ee;
  --sig-soft: rgba(34, 211, 238, 0.35);
  --sig-faint: rgba(34, 211, 238, 0.12);
  --grid-line: rgba(255, 255, 255, 0.04);
```

- [ ] **Step 3: 在 `[data-theme="paper"]` 块追加纸色覆盖**

定位到 `[data-theme="paper"] { ... }`（行 51–70）。在 `--bubble-user-bg: #efe8dc;` 之后、`color-scheme: light;` 之前追加：

```css
  --sig: #0891b2;
  --sig-soft: rgba(8, 145, 178, 0.30);
  --sig-faint: rgba(8, 145, 178, 0.10);
  --grid-line: rgba(28, 25, 23, 0.05);
```

- [ ] **Step 4: 在 `@media (prefers-color-scheme: dark)` 块追加同样的暗色覆盖**

定位到 `@media (prefers-color-scheme: dark) { :root:not(...) { ... } }`（行 72–93）。在 `--bubble-user-bg: #1a1a1a;` 之后、`color-scheme: dark;` 之前追加：

```css
    --sig: #22d3ee;
    --sig-soft: rgba(34, 211, 238, 0.35);
    --sig-faint: rgba(34, 211, 238, 0.12);
    --grid-line: rgba(255, 255, 255, 0.04);
```

- [ ] **Step 5: 升级 index.html 中 tokens.css 的版本号**

打开 `desktop/ui/index.html`，将行 11 的 `tokens.css?v=6` 改为 `tokens.css?v=7`。

- [ ] **Step 6: 启动应用，验证三主题下信号色生效**

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
./scripts/start-backend.sh
```

另开终端：
```bash
cd "/Users/sihai/Documents/My Projects/Lumina/desktop"
npm start
```

在应用设置面板切换 light / dark / paper 三主题，打开浏览器 DevTools → Elements，选中 `<html>` 元素，在 Computed 面板确认：
- light：`--sig` = `#06b6d4`
- dark：`--sig` = `#22d3ee`
- paper：`--sig` = `#0891b2`

- [ ] **Step 7: 提交**

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
git add desktop/ui/tokens.css desktop/ui/index.html
git commit -m "feat(ui): add shared AI presence design tokens

新增信号色 --sig（青 #06b6d4）+ 网格 + 节奏变量到 tokens.css，
覆盖 light/dark/paper 三主题。"
```

---

## Task 2: 思考态 · 光场呼吸

**Files:**
- Modify: `desktop/ui/index.html:119-123`（typing 区块结构）
- Modify: `desktop/ui/chat.css:548-579`（typing 样式）
- Modify: `desktop/ui/i18n.js:30` 附近（新增 chat.thinking key）

- [ ] **Step 1: 改造 index.html 的 typing 结构**

打开 `desktop/ui/index.html`，定位到行 119–123：

```html
<div id="typing" class="typing" hidden>
  <div class="typing-dots"><span></span><span></span><span></span></div>
  <span id="typing-text" class="typing-text" data-i18n="chat.processing">正在处理…</span>
  <button id="btn-pause" class="typing-pause" type="button" data-i18n="action.pause">暂停</button>
</div>
```

替换为：

```html
<div id="typing" class="typing" hidden>
  <div class="think-field" aria-hidden="true"><span class="think-core"></span></div>
  <span id="typing-text" class="typing-text" data-i18n="chat.processing">正在处理…</span>
  <button id="btn-pause" class="typing-pause" type="button" data-i18n="action.pause">暂停</button>
</div>
```

- [ ] **Step 2: 替换 chat.css 的 typing 样式**

打开 `desktop/ui/chat.css`，定位到行 548–579（`.typing` 到 `.typing-text` 整块）。将这整块替换为：

```css
.typing {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 14px 16px;
  background: var(--bg-subtle);
  border-radius: var(--radius-lg);
  width: fit-content;
}

/* 光场呼吸 —— 替代原 typing-dots 三点 */
.think-field {
  position: relative;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: radial-gradient(circle, var(--sig) 0%, var(--sig-soft) 45%, transparent 75%);
  filter: blur(1px);
  animation: think-breathe var(--pace-breathe) ease-in-out infinite;
  flex-shrink: 0;
}

.think-core {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--sig);
  box-shadow: var(--sig-glow);
}

@keyframes think-breathe {
  0%, 100% { transform: scale(0.9); opacity: 0.6; }
  50% { transform: scale(1.08); opacity: 1; }
}

/* 长时思考（>5s）—— 由 JS 添加 .is-deep 类触发 */
.typing.is-deep .think-field {
  animation-duration: var(--pace-breathe-deep);
}

.typing-text {
  margin-left: 4px;
  color: var(--text-secondary);
  font-size: 13px;
}
```

注意：原 `.typing-dots` 相关样式（行 559–573）一并删除，已被 `.think-field` 取代。`.typing-pause`（行 581+）保持不动。

- [ ] **Step 3: 在 i18n.js 新增 chat.thinking key**

打开 `desktop/ui/i18n.js`，定位到行 30 `"chat.processing"` 那一行。在它之后追加：

```js
    "chat.thinking": { en: "Thinking", zh: "思考中" },
```

- [ ] **Step 4: 在 chat.js 添加长时思考的 is-deep 类切换**

打开 `desktop/ui/chat.js`，定位到行 936 `function showTyping(visible, statusText = t("chat.processing"))`。整个函数替换为：

```js
  function showTyping(visible, statusText = t("chat.processing")) {
    typingEl.hidden = !visible;
    if (typingTextEl) {
      typingTextEl.textContent = statusText;
    }
    if (visible) {
      typingStartAt = Date.now();
      if (!typingTicker) {
        typingTicker = window.setInterval(() => {
          if (typingEl.hidden || !typingStartAt) return;
          const elapsed = Date.now() - typingStartAt;
          typingEl.classList.toggle("is-deep", elapsed > 5000);
        }, 1000);
      }
      scrollChatToBottom();
    } else {
      if (typingTicker) {
        window.clearInterval(typingTicker);
        typingTicker = null;
      }
      typingStartAt = 0;
      typingEl.classList.remove("is-deep");
    }
  }
```

确认文件顶部已声明 `let typingTicker = null;` 和 `let typingStartAt = 0;`（行 50–51 已存在，无需重复声明）。

- [ ] **Step 5: 升级 index.html 中 chat.css 和 chat.js 的版本号**

`desktop/ui/index.html`：
- 行 12：`chat.css?v=51` → `chat.css?v=52`
- 行 252：`chat.js?v=58` → `chat.js?v=59`
- 行 245：`i18n.js?v=13` → `i18n.js?v=14`

- [ ] **Step 6: 启动应用，目视验证**

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
./scripts/start-backend.sh && cd desktop && npm start
```

验证清单：
- [ ] 发送一条消息，typing 区显示青色光场呼吸（替代原三点）
- [ ] 光场中心有 4px 实心青点 + glow
- [ ] 呼吸节奏约 2.4s 一次
- [ ] 切换 dark 主题，信号色变 #22d3ee，呼吸正常
- [ ] 切换 paper 主题，信号色变 #0891b2，呼吸正常
- [ ] 在 DevTools Console 执行 `document.getElementById('typing').classList.add('is-deep')`，呼吸节奏明显变慢（3.2s）
- [ ] 输出开始后 typing 隐藏，is-deep 类被清除

- [ ] **Step 7: 提交**

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
git add desktop/ui/index.html desktop/ui/chat.css desktop/ui/chat.js desktop/ui/i18n.js
git commit -m "feat(ui): replace typing dots with breathing light field

将 typing 三点替换为青色光场呼吸动画，长时思考（>5s）自动切换至
更深沉的 3.2s 节奏。三主题下信号色一致。"
```

---

## Task 3: 输出态 · 信号条波动

**Files:**
- Modify: `desktop/ui/chat.js:1527-1537`（beginStreamingBubble 函数）
- Modify: `desktop/ui/chat.css`（新增 .bot-sig 样式，追加到 typing 样式块之后）

- [ ] **Step 1: 在 chat.js 的 beginStreamingBubble 插入 bot-sig 元素**

打开 `desktop/ui/chat.js`，定位到行 1527–1537：

```js
  function beginStreamingBubble() {
    if (streamingBubbleEl) return;
    welcome.classList.add("hidden");
    streamingText = "";
    const row = document.createElement("div");
    row.className = "message bot streaming";
    row.innerHTML = `<div class="bubble markdown"></div>`;
    messagesEl.appendChild(row);
    streamingBubbleEl = row.querySelector(".bubble");
    scrollChatToBottom();
  }
```

替换为：

```js
  function beginStreamingBubble() {
    if (streamingBubbleEl) return;
    welcome.classList.add("hidden");
    streamingText = "";
    const row = document.createElement("div");
    row.className = "message bot streaming";
    row.innerHTML = `<div class="bot-sig" aria-hidden="true"><span></span><span></span><span></span><span></span></div><div class="bubble markdown"></div>`;
    messagesEl.appendChild(row);
    streamingBubbleEl = row.querySelector(".bubble");
    scrollChatToBottom();
  }
```

- [ ] **Step 2: 在 chat.css 追加 bot-sig 样式**

打开 `desktop/ui/chat.css`，在 Task 2 替换后的 `.typing-text` 样式块之后（即原 `.typing-pause` 之前）追加：

```css
/* 输出态信号条 —— 流式输出进行中显示，结束淡出 */
.bot-sig {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 6px;
  height: 6px;
  opacity: 1;
  transition: opacity 0.3s ease;
}

.bot-sig span {
  display: block;
  height: 2px;
  border-radius: 1px;
  background: var(--text);
  transform-origin: left;
  animation: bot-sig-wave var(--pace-signal) ease-in-out infinite;
}

.bot-sig span:nth-child(1) { width: 24px; background: var(--sig); animation-delay: 0s; }
.bot-sig span:nth-child(2) { width: 14px; animation-delay: 0.1s; }
.bot-sig span:nth-child(3) { width: 20px; background: var(--sig); animation-delay: 0.2s; }
.bot-sig span:nth-child(4) { width: 10px; animation-delay: 0.3s; }

@keyframes bot-sig-wave {
  0%, 100% { opacity: 0.3; transform: scaleX(0.7); }
  50% { opacity: 1; transform: scaleX(1); }
}

/* 流式结束后淡出信号条 */
.message.bot:not(.streaming) .bot-sig {
  opacity: 0;
  height: 0;
  margin: 0;
  overflow: hidden;
}
```

- [ ] **Step 3: 升级 index.html 中 chat.css 和 chat.js 的版本号**

`desktop/ui/index.html`：
- 行 12：`chat.css?v=52` → `chat.css?v=53`（若 Task 2 已升到 52）
- 行 252：`chat.js?v=59` → `chat.js?v=60`（若 Task 2 已升到 59）

- [ ] **Step 4: 启动应用，目视验证**

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
./scripts/start-backend.sh && cd desktop && npm start
```

验证清单：
- [ ] 发送消息，typing 光场呼吸出现
- [ ] 流式输出开始，typing 消失，bot 气泡顶部出现 4 条信号条波动
- [ ] 第 1、3 条为青色，第 2、4 条为文字色
- [ ] 4 条错峰波动，节奏约 1.6s
- [ ] 流式结束，信号条 300ms 内淡出
- [ ] 已完成的历史 bot 消息不显示信号条
- [ ] dark / paper 主题下信号条颜色正确

- [ ] **Step 5: 提交**

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
git add desktop/ui/chat.js desktop/ui/chat.css desktop/ui/index.html
git commit -m "feat(ui): add signal bar wave during streaming output

bot 气泡顶部流式输出时显示 4 条信号条波动（青/文字色交替），
流式结束 300ms 淡出。"
```

---

## Task 4: 对话地图升级 · 网格底

**Files:**
- Modify: `desktop/ui/chat.css:2624-2632`（.conversation-map-view）和 `2680-2685`（.map-scroll）

- [ ] **Step 1: 给 .conversation-map-view 加网格底**

打开 `desktop/ui/chat.css`，定位到行 2624：

```css
.conversation-map-view {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  border-top: 1px solid var(--line);
  overflow: hidden;
}
```

替换为：

```css
.conversation-map-view {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background:
    linear-gradient(var(--grid-line) 1px, transparent 1px) 0 0 / var(--grid-size) var(--grid-size),
    linear-gradient(90deg, var(--grid-line) 1px, transparent 1px) 0 0 / var(--grid-size) var(--grid-size),
    var(--bg-subtle);
  border-top: 1px solid var(--line);
  overflow: hidden;
}
```

- [ ] **Step 2: 升级 index.html 中 chat.css 版本号**

`desktop/ui/index.html` 行 12：`chat.css?v=53` → `chat.css?v=54`（累加 Task 3 之后的版本）。

- [ ] **Step 3: 启动应用，目视验证**

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
./scripts/start-backend.sh && cd desktop && npm start
```

打开一个有多条消息的对话，点击侧栏「对话地图」按钮。

验证清单：
- [ ] 地图画布背景显示极细网格（15px 间距）
- [ ] light 主题下网格线极淡（rgba(0,0,0,0.05)）
- [ ] dark 主题下网格线 rgba(255,255,255,0.04)
- [ ] paper 主题下网格线 rgba(28,25,23,0.05)
- [ ] 网格不干扰节点可读性

- [ ] **Step 4: 提交**

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
git add desktop/ui/chat.css desktop/ui/index.html
git commit -m "feat(ui): add subtle grid background to conversation map

对话地图画布底改为极细网格（15px）+ bg-subtle，
三主题下网格线透明度自适应。"
```

---

## Task 5: 对话地图升级 · 节点状态视觉

**Files:**
- Modify: `desktop/ui/conversation_map.js:283-294`（节点 class 标注）
- Modify: `desktop/ui/chat.css:2711-2737`（.map-node rect 各状态样式）

- [ ] **Step 1: 在 conversation_map.js 标注节点 done / branch 状态**

打开 `desktop/ui/conversation_map.js`，定位到行 283–294：

```js
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
```

替换为：

```js
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
```

- [ ] **Step 2: 在 chat.css 追加 is-done / is-branch 节点样式**

打开 `desktop/ui/chat.css`，定位到行 2725 `.map-node.is-leaf rect { ... }` 之后，追加：

```css
.map-node.is-done rect {
  fill: var(--text);
  stroke: var(--text);
}

.map-node.is-done .map-node-q-label,
.map-node.is-done .map-node-q-text,
.map-node.is-done .map-node-a-label,
.map-node.is-done .map-node-a-text {
  fill: var(--bg);
}

.map-node.is-branch rect {
  stroke-dasharray: 4 3;
  opacity: 0.7;
}
```

- [ ] **Step 3: 调整 is-active 样式使用信号色**

定位到行 2719–2723：

```css
.map-node.is-active rect {
  stroke: var(--text-secondary);
  stroke-width: 1.25;
  fill: var(--bg-subtle);
}
```

替换为：

```css
.map-node.is-active rect {
  stroke: var(--sig);
  stroke-width: 1.5;
  fill: var(--bg);
}
```

说明：SVG rect 不支持 box-shadow 外环，`filter: drop-shadow` 在 SVG `<g>` 上跨浏览器表现不一致，故只用 stroke 信号色 + 加粗表达活跃态，保持克制。

- [ ] **Step 4: 升级 index.html 中 conversation_map.js 和 chat.css 版本号**

`desktop/ui/index.html`：
- 行 253：`conversation_map.js?v=5` → `conversation_map.js?v=6`
- 行 12：`chat.css?v=54` → `chat.css?v=55`

- [ ] **Step 5: 启动应用，目视验证**

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
./scripts/start-backend.sh && cd desktop && npm start
```

打开有分支的对话（至少 3 个节点，含一次 fork）。

验证清单：
- [ ] 当前叶子节点（is-active + is-leaf）：青色边框 1.5px
- [ ] 活跃路径上的祖先节点（is-done）：黑底白字
- [ ] 非活跃分支节点（is-branch）：虚线边 + 透明度 0.7
- [ ] 普通节点：白底灰边
- [ ] 三主题下视觉一致（dark 下 is-done 为亮底暗字自动反转）
- [ ] 点击节点切换分支，状态正确更新

- [ ] **Step 6: 提交**

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
git add desktop/ui/conversation_map.js desktop/ui/chat.css desktop/ui/index.html
git commit -m "feat(ui): upgrade conversation map node states

节点区分 done/active/branch 三态：活跃路径祖先黑底白字，
当前叶子青色边框，非活跃分支虚线弱化。"
```

---

## Task 6: 对话地图升级 · 活跃路径信号流

**Files:**
- Modify: `desktop/ui/chat.css:2699-2708`（.map-edge 和 .map-edge.is-active）

- [ ] **Step 1: 改造 .map-edge.is-active 为信号流动画**

打开 `desktop/ui/chat.css`，定位到行 2699–2708：

```css
.map-edge {
  fill: none;
  stroke: var(--line);
  stroke-width: 1;
}

.map-edge.is-active {
  stroke: var(--text-secondary);
  stroke-width: 1.25;
}
```

替换为：

```css
.map-edge {
  fill: none;
  stroke: var(--line);
  stroke-width: 1;
}

/* 活跃路径边 —— 信号流沿边流动 */
.map-edge.is-active {
  stroke: var(--sig);
  stroke-width: 1.5;
  stroke-dasharray: 6 4;
  animation: edge-flow var(--pace-flow) linear infinite;
}

@keyframes edge-flow {
  to { stroke-dashoffset: -10; }
}
```

注意：SVG path 的 `stroke-dasharray` + `stroke-dashoffset` 动画是合成层友好方式，比 `background-position` 更适合 SVG。

- [ ] **Step 2: 升级 index.html 中 chat.css 版本号**

`desktop/ui/index.html` 行 12：`chat.css?v=55` → `chat.css?v=56`。

- [ ] **Step 3: 启动应用，目视验证**

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
./scripts/start-backend.sh && cd desktop && npm start
```

验证清单：
- [ ] 活跃路径上的边显示为青色虚线流动
- [ ] 流动方向从父节点向子节点（stroke-dashoffset 负值）
- [ ] 流动节奏约 1.2s 一周期
- [ ] 非活跃路径边保持静态灰色
- [ ] 切换分支后，流动边正确更新到新活跃路径
- [ ] dark / paper 主题下信号色正确

- [ ] **Step 4: 提交**

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
git add desktop/ui/chat.css desktop/ui/index.html
git commit -m "feat(ui): animate active path edges with signal flow

活跃路径边改为青色虚线流动动画（stroke-dashoffset），
节奏 1.2s，方向从根向叶子。"
```

---

## Task 7: prefers-reduced-motion 全局降级

**Files:**
- Modify: `desktop/ui/chat.css`（文件末尾追加降级块）

- [ ] **Step 1: 在 chat.css 末尾追加降级样式**

打开 `desktop/ui/chat.css`，在文件最末尾追加：

```css
/* ========== AI 在场视觉系统 · 动效降级 ========== */
@media (prefers-reduced-motion: reduce) {
  .think-field {
    animation: none;
    opacity: 0.7;
  }

  .bot-sig span {
    animation: none;
    opacity: 0.5;
  }

  .map-edge.is-active {
    animation: none;
    stroke-dasharray: none;
  }
}
```

- [ ] **Step 2: 升级 index.html 中 chat.css 版本号**

`desktop/ui/index.html` 行 12：`chat.css?v=56` → `chat.css?v=57`。

- [ ] **Step 3: 启动应用，开启系统减少动效设置验证**

macOS：系统偏好设置 → 辅助功能 → 显示器 → 勾选「减少动态效果」。

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
./scripts/start-backend.sh && cd desktop && npm start
```

验证清单：
- [ ] 思考态光场停止呼吸，静态显示半透明光斑
- [ ] 输出态信号条停止波动，静态显示半透明条
- [ ] 对话地图活跃边停止流动，显示为静态实线
- [ ] 关闭「减少动态效果」，所有动画恢复

- [ ] **Step 4: 提交**

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
git add desktop/ui/chat.css desktop/ui/index.html
git commit -m "feat(ui): add prefers-reduced-motion fallback for AI presence

所有 AI 在场动效在系统开启减少动效时停止，改为静态显示。"
```

---

## 完成验证

全部 7 个任务完成后，执行整体验证：

- [ ] **集成验证清单**

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
./scripts/start-backend.sh && cd desktop && npm start
```

1. 发送消息 → typing 光场呼吸（青色，2.4s）→ 5s 后变深沉（3.2s）
2. 流式输出开始 → typing 消失 → bot 气泡顶部信号条波动（1.6s）
3. 流式结束 → 信号条 300ms 淡出
4. 打开对话地图 → 网格底 + 节点三态 + 活跃路径信号流（1.2s）
5. light / dark / paper 三主题切换，信号色正确
6. 开启系统「减少动态效果」，所有动画停止
7. 历史对话无残留信号条 / 光场

- [ ] **后端测试无回归**

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
uv run pytest
uv run ruff check src tests
uv run mypy src
```

预期：全部通过（本计划纯前端改造，不影响后端）。

---

## 范围外（留作独立计划）

- **§4.4 Skill 编排视图** —— 依赖后端 orchestrator 模式推送 `skill_flow` SSE 事件，需后端先行设计事件协议。待后端就绪后单独出计划。
