# AI 在场视觉系统 · 设计文档

> 日期：2026-07-14
> 主题：为 Lumina 前端注入统一的「AI 在场」视觉语言
> 状态：待评审

## 1. 背景与目标

Lumina 当前前端视觉极简扁平、黑白灰为主，已有 mark-lumen 圆形光感 logo、月相 + 节气情感化点缀、三套主题（light / dark / paper）。但缺少一个统一的「AI agent 身份感」——用户感知不到 AI 在思考、在工作、在输出。

**目标**：建立一套共享信号色 + 共享节奏语言的视觉系统，让 AI 的三种核心行为（思考 / 输出 / 工作流编排）各自有清晰的视觉表达，且彼此连贯，传达「AI 是在场的、有节奏的、结构化的」。

**非目标**：
- 不做顶栏状态指示（已有 token 用量 + 模型名足够）
- 不做 Hero 光场改造（保留现有静态 mark-lumen）
- 不引入姓名 / 个人印记文字
- 不堆砌花哨动画，所有动效必须服务于状态可读性

## 2. 设计原则

1. **唯一信号色** —— 全系统只用一个彩色 `#06b6d4`（青），其余走现有黑白灰 token。任何新增彩色必须经评审。
2. **节奏即语言** —— 不同行为用不同节奏区分：思考 = 慢呼吸（1.8–3.2s），工作流 = 中速流（1.0–1.4s），输出 = 快波动（1.6s）。
3. **结构化优先** —— 工作流类视觉用网格 + 节点 + 边，不用有机形态。
4. **克制** —— 动效幅度小、频率低、不抢占文字注意力。可读性 > 炫酷。
5. **三主题一致** —— light / dark / paper 三套主题下系统都能正常工作，仅调整底色与信号色透明度，不引入新色。

## 3. 共享设计 Token

新增到 [tokens.css](file:///Users/sihai/Documents/My%20Projects/Lumina/desktop/ui/tokens.css)：

```css
:root {
  /* 信号色 —— 唯一新增彩色 */
  --sig: #06b6d4;
  --sig-soft: rgba(6, 182, 212, 0.35);
  --sig-faint: rgba(6, 182, 212, 0.12);
  --sig-glow: 0 0 12px var(--sig);

  /* 网格 */
  --grid-size: 15px;
  --grid-line: rgba(0, 0, 0, 0.05);

  /* 节奏 */
  --pace-breathe: 2.4s;   /* 思考光场 */
  --pace-flow: 1.2s;      /* 信号流 */
  --pace-signal: 1.6s;    /* 输出信号条 */
}

[data-theme="dark"] {
  --sig: #22d3ee;          /* 暗底下提亮一档 */
  --sig-soft: rgba(34, 211, 238, 0.35);
  --sig-faint: rgba(34, 211, 238, 0.12);
  --grid-line: rgba(255, 255, 255, 0.04);
}

[data-theme="paper"] {
  --sig: #0891b2;          /* 纸底降一档饱和 */
  --sig-soft: rgba(8, 145, 178, 0.30);
  --sig-faint: rgba(8, 145, 178, 0.10);
  --grid-line: rgba(28, 25, 23, 0.05);
}
```

## 4. 落点设计

### 4.1 思考态 · 光场呼吸

**位置**：[chat.css](file:///Users/sihai/Documents/My%20Projects/Lumina/desktop/ui/chat.css) `.typing` 区块（现有 typing 三点，行 548–579）

**改造**：将现有 `.typing-dots` 三点替换为单个圆形光场。

**视觉**：
- 36×36 圆形，`radial-gradient` 从 `--sig` 到透明
- `filter: blur(1px)` 柔化边缘
- 中心 4px 实心点 + `--sig-glow` 阴影
- 呼吸动画 `--pace-breathe`，`scale(.9) → scale(1.08)` + `opacity(.6 → 1)`

**节奏映射**：
- 默认思考：2.4s
- 长时思考（持续 >5s 未开始输出）：动画切到 3.2s（更深沉），传达「正在深度推理」

前端只做这两档，不区分 MCP 等待等子状态（前端无法独立判断，且细分价值有限）。

**结构**：
```html
<div class="typing" id="typing">
  <div class="think-field"></div>
  <span class="think-label" data-i18n="chat.thinking">思考中</span>
</div>
```

**降级**：`prefers-reduced-motion: reduce` 时停止动画，只显示静态光点 + 文字。

### 4.2 输出态 · 信号条波动

**位置**：bot 气泡内部顶部，流式输出进行中显示，输出结束淡出。

**视觉**：
- 4 条短横线，宽度 10–24px 不等，高度 2px
- 第 1、3 条用 `--sig`，第 2、4 条用 `--text`
- 每条独立 `scaleX` + `opacity` 波动，错峰 0.1s
- 节奏 `--pace-signal`
- 末尾跟随一个 6×12 青色光标（替代现有文字光标）

**触发**：
- 流式 token 到达时显示
- 流式结束 200ms 后淡出（300ms transition）

**结构**：
```html
<div class="msg bot streaming">
  <div class="bot-sig" aria-hidden="true">
    <span></span><span></span><span></span><span></span>
  </div>
  <div class="bot-text"><!-- markdown 渲染 --></div>
</div>
```

**注意**：仅在流式进行中显示，普通已完成的 bot 消息不显示信号条。

### 4.3 对话地图升级

**位置**：[conversation_map.js](file:///Users/sihai/Documents/My%20Projects/Lumina/desktop/ui/conversation_map.js) + 对应 CSS

**改造**：现有树形布局保留，视觉层升级。

**视觉**：
- 画布底：`--bg-subtle` + 极细网格（`--grid-size` 15px，`--grid-line`）
- 节点：圆角方块卡片（替代现有圆点），padding 4×8，max-width 90px，白底 + 1px `--line` 边
- 节点状态：
  - `done` —— 黑底白字（已完成的祖先节点）
  - `active` —— `--sig` 边 + `--sig-faint` 2px 外环（当前叶子）
  - `branch` —— 虚线边 + opacity .7（非活跃分支）
  - 默认 —— 白底灰边
- 边：1px `--line-strong`
- 活跃路径边：`linear-gradient(transparent, --sig, transparent)` + `background-size: 50px` + flow 动画 `--pace-flow`

**活跃路径定义**：从根到当前 active 叶子的路径上的所有边与节点。沿用现有 `computeActivePathSet`（[conversation_map.js#L110](file:///Users/sihai/Documents/My%20Projects/Lumina/desktop/ui/conversation_map.js#L110)）的输出。

**布局算法**：不动，沿用 `computeLayout`。

### 4.4 Skill 编排视图（新建）

**位置**：新建 `desktop/ui/skill_flow.js` + `skill_flow.css`，在 orchestrator 模式下作为右侧抽屉或 conversation_map 同级的第二种视图。

**触发**：
- agent_mode === `orchestrator` 时，顶栏「对话地图」按钮旁新增「编排」按钮
- 或 orchestrator 模式下自动展开 skill 链路面板

**视觉**：
- 与对话地图共享网格底 + 节点形态
- 节点类型：
  - `entry` —— `--sig` 边（入口）
  - `running` —— `--sig` 边 + 3px `--sig-faint` 外环 + `--sig-soft` 阴影
  - `done` —— 黑底白字
  - `pending` —— 白底灰边
- 节点内容：图标（几何符号）+ skill 名称（等宽小字）
- 边：同对话地图，运行中的边走信号流
- 右下角状态徽章：`WORKFLOW · 2/5 RUNNING`

**数据来源**：后端 orchestrator 执行时需要暴露 skill 链路结构 + 实时状态。这是后端依赖项，详见 §6。

**降级**：后端未提供 skill 链路数据时，显示空状态「暂无活跃编排」。

## 5. 状态切换逻辑

```
用户发送消息
   ↓
显示思考态（光场呼吸）
   ↓
[若 orchestrator 模式且有多 skill]
   → 同时在 skill 编排视图显示节点 + 信号流
   ↓
开始流式输出
   → 思考态淡出
   → bot 气泡出现，顶部信号条波动
   ↓
流式结束
   → 信号条 200ms 后淡出
   → 光标消失
   ↓
[若 orchestrator]
   → skill 节点全部变 done
```

所有状态切换通过现有 `chat.js` 的事件钩子接入，不新增状态机。

## 6. 技术实现要点

### 6.1 前端
- 新增 `tokens.css` 变量（§3）
- 改造 `chat.css` `.typing` 区块 → 光场呼吸
- 新增 `chat.css` `.bot-sig` + `.bot-cursor` 样式
- 改造 `conversation_map.js` 节点渲染 + `conversation_map.css`
- 新建 `skill_flow.js` / `skill_flow.css` / 在 `index.html` 引入
- `i18n.js` 新增 `chat.thinking` / `workflow.running` / `workflow.empty` 等 key

### 6.2 后端依赖
- skill 编排视图需要后端在 orchestrator 模式下推送 skill 链路状态
- 建议复用现有 SSE 流，新增事件类型 `skill_flow`，payload 示例：
  ```json
  {
    "nodes": [
      {"id": "s1", "name": "plan", "status": "done"},
      {"id": "s2", "name": "search", "status": "running"}
    ],
    "edges": [{"from": "s1", "to": "s2", "flow": true}]
  }
  ```
- 若后端暂不具备，先做 4.1 / 4.2 / 4.3，4.4 作为 P2 后续迭代

### 6.3 性能
- 所有动画用 `transform` + `opacity`，不用 `width`/`height`
- 信号流动画用 `background-position`，已验证对合成层友好
- 同时存在的动画不超过 5 个（思考 1 + 输出 4 信号条；或工作流 N 节点）
- `prefers-reduced-motion` 全局降级

### 6.4 可访问性
- 所有装饰性动画 `aria-hidden="true"`
- 信号条 / 光场不承载信息，仅作氛围；信息由文字承担
- 色彩对比：`--sig` 在三主题下对底色对比度均 ≥ 4.5:1（青 #06b6d4 对白 ≈ 3.8:1，对黑 ≈ 8.2:1；暗底用 #22d3ee 提至 5.5:1；纸底用 #0891b2 提至 5.2:1）

## 7. 测试要点

- 三主题（light / dark / paper）下视觉一致性
- `prefers-reduced-motion` 降级
- 长时思考（>5s）节奏自动切换
- 流式输出中途取消时信号条正确淡出
- 对话地图大数量节点（>30）性能
- skill 编排视图后端无数据时的空状态
- orchestrator → auto 模式切换时正确关闭编排视图

## 8. 范围与优先级

| 落点 | 优先级 | 依赖 |
|---|---|---|
| 4.1 思考态光场呼吸 | P0 | 无 |
| 4.2 输出态信号条 | P0 | 无 |
| 4.3 对话地图升级 | P1 | 无 |
| 4.4 Skill 编排视图 | P2 | 后端 `skill_flow` 事件 |

## 9. 不做的事

- 顶栏状态指示（已决定不做）
- Hero 光场改造（已决定不做）
- 引入姓名 / 个人印记文字
- 新增彩色（除 `--sig` 外）
- 改动现有布局结构、信息架构
- 改动后端 agent loop 逻辑（仅新增 skill_flow 事件推送）
