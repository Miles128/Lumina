# Lumina · 灵犀 — Product Requirements Document

**Version:** 0.2.0  
**Author:** 四海 (myx28@qq.com)  
**Last updated:** 2026-07-08  
**Status:** Active development · v0.2 harness focus

<p align="center">
  <img src="assets/logo.png" alt="Lumina logo" width="96" />
</p>

---

## 1. Product Vision · 产品愿景

灵犀（Lumina）是一款**本地优先的个人 AI 秘书**，面向单一用户。应用在本机运行，接入 OpenAI 兼容大模型，通过 **Shibei 语义知识库**、Lumina 持久记忆、可选连接器同步和工具调用，持续理解用户上下文——而不是变成通用聊天机器人。

### 设计原则

| 原则 | 说明 |
|------|------|
| **Local & private** | 数据默认留在本机（`~/.lumina/`、Shibei `~/.shibei/db`） |
| **Action-oriented** | 读文件、跑命令、检索知识、联网；高风险操作必须确认 |
| **Transparent** | 工具进度、子 Agent 树、流式回复对用户可见 |
| **Grounded** | 文件/记忆类回答必须基于工具输出 |
| **Shibei-first read** | 个人文档优先 `shibei_search`；连接器 sync 是备选 |
| **Harness-first** | 自研 Turn + AgentLoop + `spawn_subagent`；**不用 LangGraph** |
| **Minimal UI** | 紧凑 Electron 桌面聊天；双语 English · 中文 |

### 非目标（v0.2）

- 多用户 / 云端后端 / 移动优先
- 无需确认的全自动 Agent
- LangGraph / 嵌入 Hermes·OpenCode·Pi runtime
- IM 网关作为主 UI（FR-16 backlog）
- Orchestrator 作为独立 Profile（已移除；委派能力并入 **Build**）

---

## 2. Target User · 目标用户

**主要用户：** 产品拥有者 — 基于 Shibei 索引提问、在可控前提下执行文件/Shell 任务、跨会话积累记忆、可选同步飞书/读书等连接器数据。

---

## 3. Agent Profiles · 主会话模式

> 权限通过**工具列表过滤**实现（OpenCode permission ruleset），不靠 prompt 许愿。

| Profile | 中文 | 用途 | 工具边界 |
|---------|------|------|----------|
| **auto** | 自动 | **默认**；系统按问题类型选 Ask/Plan/Build | 运行时解析为 ask/plan/build 之一 |
| **build** | 执行 | 读写、同步、委派 | 全工具 + `spawn_subagent` + `spawn_cli_agent` |
| **ask** | 问答 | 检索与只读分析 | 只读：FS/记忆/Shibei/联网/浏览器/连接器状态/`ask_user` |
| **plan** | 规划 | 出方案、拆步骤 | Ask 全套 + `todo` / `skills_*`；仍不写盘、不 shell |

**Auto 路由（规则优先，无额外 LLM）：**

- 闲聊/记忆检索/light 路由 → 等效 **Ask**
- 含「规划/方案/步骤/架构」且无写操作语义 → **Plan**
- 含写/改/删/shell/同步/委派或 filesystem 问题 → **Build**

**迁移：** 旧配置 `orchestrator` 自动映射为 `build`。

配置：`~/.lumina/agent.json` → `"agent_profile": "auto|build|ask|plan"`，或聊天输入框旁模式切换。

---

## 4. Tool Inventory · 工具清单

### 4.1 核心工具（`ChatToolRegistry.build_tools()`）

| 类别 | 工具名 | 需确认 | 说明 |
|------|--------|--------|------|
| 文件系统 | `list_dir`, `file_read`, `search_files`, **`glob_files`** | 读：否 | 列目录、读文件、rg 搜内容、glob 找文件 |
| 文件系统 | `file_write`, `patch`, `file_delete` | 是* | 写/改/删（*永久授权后可免部分确认） |
| 执行 | `shell` | 是* | 只读命令可免确认 |
| 记忆 | `search_memory`, `session_search`, `memory` | 读：否 | Lumina SQLite + 会话记忆 + MD 写入 |
| Shibei | `shibei_search`, `shibei_import`, `shibei_list_sources` | 否 | 语义 KB（设置开启时注入） |
| 联网 | `web_search`, `web_fetch` | 否 | 多引擎降级；FR-29 API 化进行中 |
| 连接器 | **`list_connectors`**, **`connector_status`**, **`sync_source`** | sync：是 | Agent 可直接查状态/触发同步（Build） |
| 协作 | `todo`, `skills_list`, `skill_view` | 否 | 待办与技能 |
| 交互 | `clarify`, **`ask_user`** | 否 | 追问；`ask_user` 支持选项，前端可点选 |
| 委派 | `spawn_subagent`, `spawn_cli_agent` | CLI：是 | 子 Agent / 外进程 CLI（Build） |
| MCP | `mcp_{server}_{tool}` | 视工具 | stdio 动态桥接 |
| 浏览器 | `browser_*` | 否 | 按需注入；含 **`browser_screenshot`** |

### 4.2 Sub-agent 工具集（`depth=1`，子 Agent 不可再 spawn）

| Archetype | 工具 |
|-----------|------|
| explore / verify / plan | 只读 FS + 记忆 + 联网 |
| worker | 只读 + `file_write` / `patch` / `shell` |
| 自定义 | `~/.lumina/subagents/*.md` frontmatter `tools:` 白名单 |

### 4.3 PromptGate 路由（与 Profile 正交）

| Route | 说明 |
|-------|------|
| `direct` | 闲聊/常识，零工具 |
| `light` | 记忆检索，精简工具集 |
| `full_agent` | 完整 AgentLoop（受 Profile 过滤） |

---

## 5. Product Scope · 产品范围（状态）

### 5.1 Chat & Agent

| 能力 | 状态 |
|------|------|
| AgentLoop（8 步 full / 3 步 light） | Done |
| **Build / Ask / Plan** profiles | **Done** |
| **Auto profile**（规则路由 ask/plan/build） | **Done** |
| **Turn 持久化**（`turns.json` + pause bundle） | **Done** |
| **Context compaction**（长 turn 内历史压缩） | **Done** |
| PromptGate（规则优先，可选 LLM） | Done |
| Grounding + Verified/Unverified | Done |
| SSE 流式 + 工具进度 | Done |
| **Harness P0**：`TurnContext` · `SessionStore` · `TurnRunner` · SSE schema v2 | **Done** |
| Sub-agent pause/resume + 进度树 | Done |
| `spawn_cli_agent` 核心 + 设置 UI | Core Done |
| **`ask_user` 结构化追问 + UI 选项** | **Done** |
| Chat Markdown（markdown-it + DOMPurify） | Done |
| 多线程持久化（`/api/chat/threads`） | Done |

### 5.2 Memory & Knowledge

| 能力 | 状态 |
|------|------|
| Shibei KB 直连 + workspace UI | Done |
| Shibei-first 读记忆路由 | Done |
| 写记忆不被 sync_empty 误拦 | Done |
| Lumina MEMORY/USER + SQLite 连接器（备选） | Done |
| Shibei 空结果 UX（自动 import / 引导） | **Done** |

### 5.3 Sync & Connectors

| 能力 | 状态 |
|------|------|
| 飞书 / 读书 / 小红书 / 邮箱 / 云盘 / 本地文档 | Done |
| 设置页手动同步 | Done |
| **Agent 工具 `sync_source` / `list_connectors`** | **Done** |
| Briefing / Think 优先 Shibei | **Paused**（先完善 harness） |

### 5.4 Browser · 浏览器

| 能力 | 状态 |
|------|------|
| `agent-browser` CLI 集成 | Done |
| Ask/Plan 调研类意图更容易注入 browser 工具 | Done |
| `browser_screenshot` | Done |
| 安装引导 / 无 CLI 降级文案 | Done |

### 5.5 其他

| 能力 | 状态 |
|------|------|
| MCP stdio | Done |
| MCP HTTP/SSE | Planned (FR-15) |
| 定位 UI | **已关闭**；天气走 `web_search` 默认 |
| macOS 打包（需本机 Python） | Done；内嵌 Python Planned (FR-27) |

---

## 6. User Flows · 用户流程

**读记忆（推荐）**

```
用户：「读取记忆：面试准备」
  → PromptGate LIGHT → shibei_search → grounded 回复
（无需先同步）
```

**Agent 触发同步（Build）**

```
用户：「同步飞书数据」
  → sync_source(source=feishu) → [确认] → 写入 SQLite → 回复摘要
```

**结构化追问**

```
Agent 缺信息 → ask_user(questions=[{prompt, options}])
  → 聊天区渲染可点选按钮 → 用户选择 → 继续对话
```

**Sub-agent 确认**

```
spawn_subagent(worker) → file_write 需确认
  → UI 暂停 + 子 Agent 树 → Allow → resume → 摘要回父 Agent
```

**CLI 委派（Build）**

```
spawn_cli_agent(provider=codex, goal=…) → [确认] → subprocess → 摘要回 LLM
```

---

## 7. System Architecture · 系统架构

```
┌──────────── Electron Desktop ────────────┐
│  chat · settings · workspace (Shibei)   │
│  Build/Ask/Plan · ask_user 选项 UI      │
│  SSE: /api/chat/progress/{trace_id}     │
└──────────────────┬───────────────────────┘
                   │ localhost:8765
┌──────────────────▼───────────────────────┐
│  ChatService                             │
│    → PromptGate → sync_routing           │
│    → TurnRunner (Harness P0)             │
│         → TurnOrchestrator → AgentLoop   │
│         → spawn_subagent / spawn_cli_agent│
│  ChatToolRegistry (profile 过滤工具)      │
│  Scheduler: sync · briefing · think      │
└──────────┬─────────────┬─────────────────┘
           │             │
    ~/.lumina/      Shibei ~/.shibei/db
    SQLite sync     ← 读记忆主路径
```

**知识读取优先级：** `shibei_search` → `session_search` → `search_memory` → MEMORY/USER.md

---

## 8. Functional Requirements · 功能需求

| ID | 需求 | 优先级 | 状态 |
|----|------|--------|------|
| FR-01 | 流式聊天 | P0 | Done |
| FR-02 | Shell/write/delete 确认 | P0 | Done |
| FR-03 | 只读工具免确认 | P0 | Done |
| FR-04 | SSE 工具进度 | P0 | Done |
| FR-05 | 暂停与超时 UI | P0 | Done |
| FR-06 | 连接器同步（可选） | P0 | Done |
| FR-07 | 记忆/画像编辑 | P0 | Done |
| FR-08 | Skills UI | P0 | Done |
| FR-09 | MCP stdio | P0 | Done |
| FR-22 | Shibei KB 集成 | P0 | Done |
| FR-23 | Shibei-first 读记忆路由 | P0 | Done |
| FR-10 | 双语 UI | P1 | Done |
| FR-11 | Think + 每日摘要 | P1 | Done |
| FR-12 | 多线程持久化 | P1 | Done |
| FR-13 | Hermes 一键导入 | P1 | Done |
| FR-14 | Sub-agent Phase 2 | P2 | Done |
| FR-24 | Sub-agent pause/resume + 树 UI | P1 | Done |
| FR-25 | KB workspace UI | P1 | Done |
| FR-26 | Chat Markdown | P1 | Done |
| FR-30 | CLI Agent 委派 | P1 | **Frozen**（不做 provider 集成；保留核心代码） |
| **FR-31** | **Build / Ask / Plan profiles** | P1 | **Done** |
| **FR-40** | **Auto profile**（规则路由） | P1 | **Done** |
| **FR-41** | **Turn 持久化** | P1 | **Done** |
| **FR-42** | **Context compaction** | P1 | **Done** |
| **FR-32** | **连接器 Agent 工具**（list/status/sync） | P1 | **Done** |
| **FR-33** | **`glob_files` + `ask_user`** | P1 | **Done** |
| **FR-34** | **Harness P0**（Turn/SessionStore/SSE v2） | P1 | **Done** |
| **FR-35** | **Browser screenshot + Ask 路由** | P2 | **Done** |
| FR-28 | Explore 便宜模型路由 | P2 | **Pending** |
| FR-29 | Web search API（Brave/Tavily） | P2 | **Next round** |
| FR-15 | MCP HTTP/SSE | P2 | Planned |
| FR-27 | 打包内嵌 Python | P2 | Planned |
| FR-16 | IM 网关 | P3 | Backlog |
| FR-36 | Shibei 空结果 UX | P1 | Done |
| FR-37 | Git 只读工具 | P3 | Backlog（非常靠后） |
| FR-38 | 前端 Turn 树（消费 schema v2） | P2 | Done |
| FR-39 | Plan 模式 PermissionGuard 硬拦截 | P2 | Done |

---

## 9. CLI Agent Delegation · 外接 CLI（FR-30 · Frozen）

> **决策（2026-07）：不做 CLI provider 端到端集成。** 优先自研 harness（Turn 持久化、compaction、Auto profile）。`spawn_cli_agent` 核心代码保留，默认关闭，不设近期 roadmap 项。

| Profile | `spawn_cli_agent` |
|---------|-------------------|
| **build** | 可用（确认后） |
| **ask** / **plan** / **auto→ask/plan** | 禁用 |

原则：父 Agent 只见 CLI **摘要 + 退出码**；stdout 全量落盘 `~/.lumina/logs/cli-agent/`。

**明确不做：** codex/kimi/claude CLI provider 端到端测试与 prompt 调优（FR-30d 取消）。

---

## 10. Success Metrics · 成功指标

| 指标 | 目标 | 当前 |
|------|------|------|
| 单元测试 | CI 全绿 | **356** passed |
| 无 sync 读 Shibei | 零同步可问答 | Done |
| Ask 模式不误写 | Plan/Ask 无 shell/write | Done |
| 冷启动（不含 LLM） | <30s | Manual QA |

---

## 11. Roadmap · 路线图

### Shipped · v0.1.x – v0.2.0（已交付）

- Shibei KB + workspace UI + Shibei-first 路由
- Sub-agent pause/resume + 进度树
- Harness P0（TurnRunner · SSE schema v2 · DelegationResult）
- **Build / Ask / Plan**（移除 Orchestrator）
- **P0 工具**：`glob_files` · 连接器工具 · `ask_user`
- **Browser**：`browser_screenshot` · Ask/Plan 调研路由
- 多线程 API + UI、`spawn_cli_agent` 核心、Markdown 聊天

---

### Next · Harness 优先（2026-07 决策）

#### Now · 自研 Harness（P1）

| # | 任务 | 状态 | FR |
|---|------|------|-----|
| **H1** | Turn 持久化（`turns.json` + pause/resume bundle） | **Done** | FR-41 |
| **H2** | Context compaction（长 turn 历史压缩） | **Done** | FR-42 |
| **H3** | **Auto profile**（规则路由 ask/plan/build） | **Done** | FR-40 |

#### Paused / Deferred

| # | 任务 | 决策 |
|---|------|------|
| — | CLI provider 端到端（FR-30d） | **不做**；先自研 harness |
| — | Briefing/Think Shibei 优先 | **暂停** |
| — | `mode: primary` 自定义主 Agent | **不做**；用 Auto 替代 |
| — | FR-28 Explore 便宜模型 | **Pending** |
| — | FR-29 Web search API | **下一轮** |
| — | FR-37 Git 只读工具 | **非常靠后** |
| — | E2E 扩展 | Backlog |

#### Later · 平台（P2–P3）

| # | 任务 | FR |
|---|------|-----|
| N10 | MCP HTTP/SSE | FR-15 |
| N11 | 打包内嵌 Python | FR-27 |
| N13 | 定时 Agent / cron | Backlog |
| N14 | IM 网关（飞书 bot） | FR-16 |

### 明确不做（近期）

- LangGraph 迁移
- Pi / Hermes runtime 嵌入
- Orchestrator 第三种 Profile 回归
- CLI provider 集成（codex/kimi/claude 端到端）
- `~/.lumina/subagents/*.md` 的 `mode: primary` 第四种主 Agent
- 恢复桌面定位（改由 MCP/定时任务覆盖）

---

## 12. Implementation Index · 实现索引

| 区域 | 路径 |
|------|------|
| Agent loop | `src/secretary/agent/loop.py` |
| Tool registry | `src/secretary/agent/chat_tool_registry.py` |
| Profiles | `src/secretary/agent/agent_profile.py` |
| P0 tools | `src/secretary/agent/p0_tools.py` |
| Connector tools | `src/secretary/agent/tools/connector_tools.py` |
| Browser | `src/secretary/agent/browser_tools.py` |
| Harness P0 | `turn_runner.py` · `session_store.py` · `turn_models.py` |
| Turn 持久化 | `session_store.py`（`turns.json` + pause bundle） |
| Context compaction | `context_compaction.py` |
| Auto profile | `agent_profile.py` · `effective_profile()` |
| Chat UI | `desktop/ui/chat.js` · `chat.css` |
| Harness 设计 | [harness-design.md](harness-design.md) |

---

## 13. Open Decisions · 待决

| 话题 | 决策 |
|------|------|
| 读记忆默认 | Shibei first；miss 再 `search_memory` |
| Sync 定位 | 可选；Agent 用 `sync_source`，UI 同步保留 |
| CLI vs sub-agent | **CLI provider 不做**；轻量 explore → 内层 sub-agent |
| 主 Agent 扩展 | **Auto** 替代 `mode: primary` 自定义 md |
| Web search | 下一轮切 API（Brave/Tavily） |
| Briefing/Think | 暂停；先 harness |
| 打包 Python | v0.2 spike：sidecar venv |

---

*End of document · 文档结束*
