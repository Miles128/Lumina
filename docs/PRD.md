# Lumina · 灵犀 — Product Requirements Document

**Version:** 0.2.0  
**Author:** 四海 (myx28@qq.com)  
**Last updated:** 2026-07-17  
**Status:** Active development · v0.2 harness focus · Agent productivity (not secretary)

<p align="center">
  <img src="assets/logo.png" alt="Lumina logo" width="96" />
</p>

---

## 1. Product Vision · 产品愿景

灵犀（Lumina）是一款**本地优先的通用 Agent 生产力工具**。应用在本机运行，接入 OpenAI 兼容大模型，以自研 harness（Turn · profiles · confirm · sub-agent）驱动工具调用与任务执行——**不是**「个人 AI 秘书」人设产品，也**不是**无工具的通用网页聊天机器人。

**当前特色（已交付）：** 对话地图（分支 / 回滚 / 恢复）、Build / Ask / Plan / Auto、可调本地 harness、MCP / 工具扩展。  
**规划中的差异化能力：** Skill 编排（工作流 DAG，见 [workflow-dag-design.md](workflow-dag-design.md)）——设计待审，**尚未产品化**；文档与营销勿写成已上线能力。  
**可选扩展：** Shibei 知识库、持久记忆——增强生产力，而非产品主叙事。  
**外部集成原则：** 只做**标准 MCP**（stdio / SSE / Streamable HTTP）或 **CLI**（经 `shell` / MCP stdio 包装的外部命令）。**不再**为飞书/读书等平台维护一等公民自定义 Connector 产品面。

### 设计原则

| 原则 | 说明 |
|------|------|
| **Local & private** | 数据默认留在本机（`~/.lumina/`、可选 Shibei `~/.shibei/db`） |
| **Action-oriented** | 读文件、跑命令、检索知识、联网；高风险操作必须确认 |
| **Transparent** | 工具进度、子 Agent 树、对话地图、流式回复对用户可见 |
| **Grounded** | 文件/记忆类回答必须基于工具输出 |
| **Harness-first** | 自研 Turn + AgentLoop + `spawn_subagent`；**不用 LangGraph** |
| **Conversation map** | 线程内分支 / fork / rollback / restore 为已交付差异点 |
| **Skill orchestration (planned)** | Skill DAG 工作流为规划中差异点；与对话地图产品入口分离 |
| **Integrations = MCP or CLI** | 外部能力只经标准 MCP 或 CLI；不新增平台专用 connector |
| **Knowledge optional** | 启用 Shibei 时文档优先 `shibei_search` |
| **Minimal UI** | 紧凑 Electron 桌面；双语 English · 中文 |

### 非目标（v0.2）

- 多用户 / 云端后端 / 移动优先
- 「个人秘书」人格产品叙事
- 为各 SaaS（飞书/微信读书/小红书等）继续扩展一等公民自定义 Connector
- 无需确认的全自动 Agent
- LangGraph / 嵌入 Hermes·OpenCode·Pi runtime
- IM 网关作为主 UI（FR-16 Deferred）
- Orchestrator 作为独立 Profile（已移除；委派能力并入 **Build**）
- 将未实现的 Skill DAG 宣称为已上线能力
- 恢复 `spawn_cli_agent`（已 Removed）；CLI 指用户配置的 MCP stdio / shell，不是外接编码 Agent 委派

---

## 2. Target User · 目标用户

**主要用户：** 需要本地可控 Agent 做开发与知识工作的个人用户——执行文件/Shell、对话分支探索、经 MCP/CLI 扩展工具；可选接入 Shibei 与记忆。Skill 工作流编排为后续差异化能力，面向同一用户群。

---

## 3. Agent Profiles · 主会话模式

> 权限通过**工具列表过滤**实现（OpenCode permission ruleset），不靠 prompt 许愿。

| Profile | 中文 | 用途 | 工具边界 |
|---------|------|------|----------|
| **auto** | 自动 | **默认**；系统按问题类型选 Ask/Plan/Build | 运行时解析为 ask/plan/build 之一 |
| **build** | 执行 | 读写、委派、MCP/CLI | 全工具 + `spawn_subagent` |
| **ask** | 问答 | 检索与只读分析 | 只读：FS/记忆/Shibei/联网/浏览器/MCP 只读/`ask_user` |
| **plan** | 规划 | 出方案、拆步骤 | Ask 全套 + `todo` / `skills_*`；仍不写盘、不 shell |

**Auto 路由（规则优先，无额外 LLM）：**

- 闲聊/记忆检索/light 路由 → 等效 **Ask**
- 含「规划/方案/步骤/架构」且无写操作语义 → **Plan**
- 含写/改/删/shell/委派或 filesystem 问题 → **Build**

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
| 联网 | `web_search`, `web_fetch` | 否 | API：Tavily/Brave/博查 + Serper/SerpAPI/Bing/Perplexity 预留；HTML 降级 |
| 协作 | `todo`, `skills_list`, `skill_view` | 否 | 待办与技能（Skill **编排**见 F26，未产品化） |
| 交互 | `clarify`, **`ask_user`** | 否 | 追问；`ask_user` 支持选项，前端可点选 |
| 委派 | `spawn_subagent` | 否 | 子 Agent（Build） |
| MCP | `mcp_{server}_{tool}` | 视工具 | **现行外部集成主路径**：stdio / SSE / Streamable HTTP |
| CLI | `shell`（及 MCP stdio 包装的 CLI） | shell：是* | **现行外部集成主路径**；非 `spawn_cli_agent` |
| 浏览器 | `browser_*` | 否 | 按需注入；含 **`browser_screenshot`**（`agent-browser` CLI） |
| 遗留 Sync | `list_connectors`, `connector_status`, `sync_source` | sync：是 | **Legacy frozen**；勿再扩展平台专用 connector |

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
| AgentLoop（20 步 full / 3 步 light） | Done |
| **Build / Ask / Plan** profiles | **Done** |
| **Auto profile**（规则路由 ask/plan/build） | **Done** |
| **Turn 持久化**（`turns.json` + pause bundle） | **Done** |
| **Context compaction**（长 turn 内历史压缩） | **Done** |
| PromptGate（规则优先，可选 LLM） | Done |
| Grounding + Verified/Unverified | Done |
| SSE 流式 + 工具进度 | Done |
| **Harness P0**：`TurnContext` · `SessionStore` · `TurnRunner` · SSE schema v2 | **Done** |
| Sub-agent pause/resume + 进度树 | Done |
| `spawn_cli_agent` 核心 + 设置 UI | **Removed** |
| **`ask_user` 结构化追问 + UI 选项** | **Done** |
| Chat Markdown（markdown-it + DOMPurify） | Done |
| 多线程持久化（`/api/chat/threads`） | Done |

### 5.2 Memory & Knowledge

| 能力 | 状态 |
|------|------|
| Shibei KB 直连 + workspace UI | Done |
| Shibei-first 读记忆路由 | Done |
| 写记忆不被 sync_empty 误拦 | Done |
| Lumina MEMORY + SQLite 记忆（可选） | Done |
| Shibei 空结果 UX（自动 import / 引导） | **Done** |

### 5.3 Sync & Connectors（遗留冻结）

| 能力 | 状态 |
|------|------|
| 飞书 / 读书 / 小红书 / 邮箱 / 云盘 / 本地文档 | **Legacy frozen**（不再扩展；新集成走 MCP/CLI） |
| 设置页手动同步 | Legacy（可保留，不作为产品主路径） |
| Agent 工具 `sync_source` / `list_connectors` | Legacy |
| Briefing / Think 优先 Shibei | **Paused** |
| **标准 MCP / CLI 集成** | **现行路径**（见 §1） |

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
| MCP SSE / Streamable HTTP | Done（FR-15） |
| 定位 UI | **已关闭**；天气走 `web_search` 默认 |
| macOS 打包（需本机 Python） | Done；内嵌 Python **Deferred** (FR-27) |

---

## 6. User Flows · 用户流程

**读记忆（推荐）**

```
用户：「读取记忆：面试准备」
  → PromptGate LIGHT → shibei_search → grounded 回复
（无需先同步）
```

**外部集成（现行）**

```
用户配置 ~/.lumina/mcp.json（或设置 → MCP）
  → Agent 调用 mcp_{server}_{tool}
或：Build 下 shell / MCP stdio 调用外部 CLI
（不再引导「同步飞书」类一等公民连接器）
```

**遗留 Sync（冻结，非产品主路径）**

```
用户：「同步 xxx」→ sync_source（legacy）→ [确认] → SQLite
（不新增平台；文档勿宣传）
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

---

## 7. System Architecture · 系统架构

```
┌──────────── Electron Desktop ────────────┐
│  chat · settings · workspace (Shibei)   │
│  Build/Ask/Plan · conversation map      │
│  SSE: /api/chat/progress/{trace_id}     │
└──────────────────┬───────────────────────┘
                   │ localhost:8765
┌──────────────────▼───────────────────────┐
│  ChatService                             │
│    → PromptGate → grounding / routing    │
│    → TurnRunner → AgentLoop              │
│    → spawn_subagent                      │
│  ChatToolRegistry (profile 过滤)         │
│  McpManager（标准 MCP = 外部集成主路径） │
│  Scheduler: briefing · think             │
│  Legacy: SyncService / connectors 冻结   │
└──────────┬─────────────┬─────────────────┘
           │             │
    ~/.lumina/      Shibei ~/.shibei/db
    agent · mcp     （可选读记忆）
```

**知识读取优先级：** `shibei_search` → `session_search` → `search_memory` → MEMORY.md  
**外部集成：** 标准 MCP 或 CLI（见 §1）；平台专用 Connector = Legacy frozen。

---

## 8. Functional Requirements · 功能需求

| ID | 需求 | 优先级 | 状态 |
|----|------|--------|------|
| FR-01 | 流式聊天 | P0 | Done |
| FR-02 | Shell/write/delete 确认 | P0 | Done |
| FR-03 | 只读工具免确认 | P0 | Done |
| FR-04 | SSE 工具进度 | P0 | Done |
| FR-05 | 暂停与超时 UI | P0 | Done |
| FR-06 | 平台连接器同步 | P0 | **Legacy frozen**（不再扩展；见 §1） |
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
| FR-30 | CLI Agent 委派 | P1 | **Removed**（功能整体删除） |
| **FR-31** | **Build / Ask / Plan profiles** | P1 | **Done** |
| **FR-40** | **Auto profile**（规则路由） | P1 | **Done** |
| **FR-41** | **Turn 持久化** | P1 | **Done** |
| **FR-42** | **Context compaction** | P1 | **Done** |
| FR-32 | 连接器 Agent 工具（list/status/sync） | P1 | **Legacy frozen** |
| **FR-33** | **`glob_files` + `ask_user`** | P1 | **Done** |
| **FR-34** | **Harness P0**（Turn/SessionStore/SSE v2） | P1 | **Done** |
| **FR-35** | **Browser screenshot + Ask 路由** | P2 | **Done** |
| FR-28 | Explore 便宜模型路由 | P2 | **Deferred**（往后放） |
| FR-29 | Web search API（Tavily/Brave/博查 + Serper/SerpAPI/Bing/Perplexity 预留） | P2 | **Done** |
| FR-15 | MCP HTTP/SSE | P2 | **Done**（stdio + SSE + Streamable HTTP） |
| FR-27 | 打包内嵌 Python | P2 | **Deferred**（往后放） |
| FR-16 | IM 网关 | P3 | **Deferred**（往后放） |
| FR-36 | Shibei 空结果 UX | P1 | Done |
| FR-37 | Git 只读工具 | P3 | **Deferred**（往后放） |
| FR-38 | 前端 Turn 树 / 分支地图（紧凑节点 + 动态路径） | P2 | Done |
| **FR-43** | **对话标题自动跟随最新提问** | **P2** | **Done** |
| FR-39 | Plan 模式 PermissionGuard 硬拦截 | P2 | Done |
| **FR-44** | **Background Review**（每轮对话后自动提取记忆） | **P1** | **Done** |

---

## 9. Naming: CLI vs CLI Agent

| 术语 | 含义 | 状态 |
|------|------|------|
| **CLI（现行）** | 用户经 `shell` 或 **MCP stdio** 调用的外部命令行工具 | 支持；外部集成主路径之一 |
| **`spawn_cli_agent` / FR-30** | 外接编码 Agent 委派（codex/kimi 等） | **Removed**（2026-07） |

---

## 10. Success Metrics · 成功指标

| 指标 | 目标 | 当前 |
|------|------|------|
| 单元测试 | CI 全绿 | **~559** passed（随 CI） |
| 无 sync 读 Shibei | 零同步可问答 | Done |
| Ask 模式不误写 | Plan/Ask 无 shell/write | Done |
| 冷启动（不含 LLM） | <30s | Manual QA |
| 外部集成路径 | 仅 MCP / CLI | 原则已锁定；legacy connector 冻结 |

---

## 11. Roadmap · 路线图

### Shipped · v0.1.x – v0.2.0（已交付）

- Shibei KB + workspace UI + Shibei-first 路由
- Sub-agent pause/resume + 进度树
- Harness P0（TurnRunner · SSE schema v2 · DelegationResult）
- **Build / Ask / Plan**（移除 Orchestrator）
- **P0 工具**：`glob_files` · `ask_user` · MCP；平台 connector 工具 → Legacy
- **Browser**：`browser_screenshot` · Ask/Plan 调研路由
- 多线程 API + UI、**分支地图**、动态标题、Markdown 聊天

---

### Next · Harness 优先（2026-07 决策）

#### Now · 自研 Harness（P1）

| # | 任务 | 状态 | FR |
|---|------|------|-----|
| **H1** | Turn 持久化（`turns.json` + pause/resume bundle） | **Done** | FR-41 |
| **H2** | Context compaction（长 turn 历史压缩） | **Done** | FR-42 |
| **H3** | **Auto profile**（规则路由 ask/plan/build） | **Done** | FR-40 |
| **H4** | Eval harness + compaction 可观测 + hooks 接线 | **Done（MVP）** | F23 / FR-42+ |
| **H5** | Worker worktree · archetype 路由 · 结构化卡片 | **Done（MVP）** | F24 / F25 |

#### Paused / Deferred

| # | 任务 | 决策 |
|---|------|------|
| — | CLI provider 端到端（FR-30d） | **Removed** |
| — | Briefing/Think Shibei 优先 | **暂停** |
| — | `mode: primary` 自定义主 Agent | **不做**；用 Auto 替代 |
| — | FR-28 Explore 便宜模型 | **Deferred**（往后放） |
| — | FR-15 MCP HTTP/SSE | **Done** |
| — | FR-27 打包内嵌 Python | **Deferred**（往后放） |
| — | FR-16 IM 网关 | **Deferred**（往后放） |
| — | FR-37 Git 只读工具 | **Deferred**（往后放） |
| — | E2E 扩展 | Backlog |

#### Later · 平台（P2–P3）

| # | 任务 | FR |
|---|------|-----|
| N10 | MCP HTTP/SSE | FR-15（Done） |
| N11 | 打包内嵌 Python | FR-27（Deferred） |
| N13 | 定时 Agent / cron | Backlog |
| N14 | IM 网关（飞书 bot） | FR-16（Deferred） |

#### Future · 差异化与 Agent 演进（P3 / Research）

| # | 任务 | 说明 |
|---|------|------|
| **F26** | **Skill 编排（工作流 DAG）** | **实现中**：设计已拍板（`workflow-dag-design.md`）；后端 Store/Scheduler/`/api/workflows` 已落地；画布 UI 未交付 |
| F20 | **Skill 自进化** | 基于用户反馈或执行失败自动更新/生成 SKILL.md / manifest.json + run.py（依赖 F26 或独立 skill 运行时） |
| F21 | **反思记忆（Reflexion-style）** | **Done（MVP）**：失败 turn → reflect 子 agent → episodes 表扩展 → top-3 注入 system prompt |
| F22 | **代码级自修复** | 在显式用户确认下，让子 Agent 修改 Lumina 自身源码并跑测试验证；默认关闭 |
| F23 | **评测 harness（eval-driven）** | **Done（MVP）**：`tests/eval` 离线 golden cases |
| F24 | **智能 archetype 选择** | **Done（MVP）**：`select_archetype` 规则路由 |
| F25 | **结构化输出卡片** | **Done（MVP）**：`SUMMARY_CARD` / `CODE_DIFF_CARD` / `REFERENCE_CARD` + `emit_card` |

### 明确不做（近期）

- LangGraph 迁移
- Pi / Hermes runtime 嵌入
- Orchestrator 第三种 Profile 回归
- CLI provider / `spawn_cli_agent`（codex/kimi/claude 端到端，FR-30 已 Removed）
- 为飞书/读书等 SaaS **新增或扩展**平台专用 Connector / builtin MCP provider 产品面
- `~/.lumina/subagents/*.md` 的 `mode: primary` 第四种主 Agent
- 恢复桌面定位（改由 MCP/定时任务覆盖）
- 将 Skill 编排（F26）宣称为已上线

---

## 12. Implementation Index · 实现索引

| 区域 | 路径 |
|------|------|
| Agent loop | `src/secretary/agent/loop.py` |
| Tool registry | `src/secretary/agent/chat_tool_registry.py` |
| Profiles | `src/secretary/agent/agent_profile.py` |
| P0 tools | `src/secretary/agent/p0_tools.py` |
| MCP | `mcp_manager.py` · `~/.lumina/mcp.json` |
| Legacy connectors | `connectors/*` · `connector_tools.py`（冻结） |
| Browser | `src/secretary/agent/browser_tools.py` |
| Harness P0 | `turn_runner.py` · `session_store.py` · `turn_models.py` |
| Turn 持久化 | `session_store.py`（`turns.json` + pause bundle） |
| Context compaction | `context_compaction.py` |
| 反思记忆 | `src/secretary/agent/reflection/` |
| Auto profile | `agent_profile.py` · `effective_profile()` |
| Chat UI | `desktop/ui/chat.js` · `chat.css` |
| Harness 设计 | [harness-design.md](harness-design.md) |

---

## 13. Open Decisions · 待决

| 话题 | 决策 |
|------|------|
| 读记忆默认 | Shibei first；miss 再 `search_memory` |
| 外部集成 | **只做标准 MCP 或 CLI**；不新增平台专用 Connector |
| Sync / 自定义 connectors | **遗留冻结**：`src/secretary/connectors/*` + SyncService 可暂时保留，不再扩展；新集成走 MCP 配置 |
| CLI vs sub-agent | **`spawn_cli_agent` 已删除**；CLI = MCP stdio / `shell`；轻量 explore → 内层 sub-agent |
| 主 Agent 扩展 | **Auto** 替代 `mode: primary` 自定义 md |
| Web search | **Done**：Tavily / Brave / 博查 API（env key）+ HTML 降级 |
| Briefing/Think | 暂停；先 harness |
| Background Review | 活跃；每轮对话后 daemon 线程提取记忆，写入 memory/user 画像 |
| 打包 Python | v0.2 spike：sidecar venv |

---

*End of document · 文档结束*
