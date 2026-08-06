# Lumina · 灵犀 — Product Requirements Document

**Version:** 0.3.2  
**Author:** 四海 (myx28@qq.com)  
**Last updated:** 2026-07-30  
**Status:** Active development · v0.3 harness focus · local Agent productivity

<p align="center">
  <img src="assets/logo.png" alt="Lumina logo" width="96" />
</p>

---

## 1. Product Vision · 产品愿景

灵犀（Lumina）是一款**本地优先的通用 Agent 生产力工具**。应用在本机运行，接入 OpenAI 兼容大模型，以自研 harness（Turn · profiles · confirm · sub-agent）驱动工具调用与任务执行——**不是**「个人 AI 秘书」人设产品，也**不是**无工具的通用网页聊天机器人。

**一句话：** 把强模型关进可控 harness——权限清楚、危险动作要确认、长任务可分支回看、子任务可委派但树不发散、思考链可追溯、行为参数可定制——让个人（及企业可控运行环境）把复杂事做完。

**当前特色（已交付）：** 对话地图（分支 / 回滚 / 恢复）、Build / Ask / Plan / Auto、可调本地 harness、MCP / 工具扩展、子 Agent 委派（默认单层）、Skill 工作流画布 MVP、思考链轨迹 MVP、Harness 可调参 MVP。  
**规划中的差异化能力：** **受控深树 / 结构化对抗 / WriteGate / Mission Strip**（FR-53–56，见 [规格](superpowers/specs/2026-07-30-controlled-tree-adversarial-mission-strip-design.md)）；Skill DAG 高级能力仍属后续——文档与营销勿写成「全量已上线」。  
**可选扩展：** Shibei 知识库、持久记忆——增强生产力，而非产品主叙事。  
**外部集成原则：** 只做**标准 MCP**（stdio / SSE / Streamable HTTP）或 **CLI**（经 `shell` / MCP stdio 包装的外部命令）。**不再**为飞书/读书等平台维护一等公民自定义 Connector 产品面。

> **用语：** 产品主叙事是 **harness · 委派 · 确认 · 对话地图 · 工作流 · 可追溯思考链 · 可定制运行参数**。可偶尔用「协作 / 编制」描述人机与岗位化子任务推进；UI 可用 Mission Strip（岗位名 + 进度）。**不以**「Agent 协作平台 / 自由 Swarm / 聊天室式多智能体」作定位或宣传。

### 设计原则

| 原则 | 说明 |
|------|------|
| **Local & private** | 数据默认留在本机（`~/.lumina/`、可选 Shibei `~/.shibei/db`） |
| **Action-oriented** | 读文件、跑命令、检索知识、联网；高风险操作必须确认 |
| **Transparent** | 工具进度、子 Agent 树、对话地图、流式回复对用户可见 |
| **Traceable reasoning** | **思考链可记录、可追溯、可分析**——模型推理 / 工具决策 / 确认与委派节点形成结构化轨迹，支持回放、审计与事后分析；对企业可控运行环境（合规、事故复盘、质量评估）是一等公民能力，而非调试彩蛋 |
| **Configurable harness** | **Harness 功能暴露大量可定制参数**（确认策略、委派上限、compaction、工具轮次、超时、模型/profile 路由、思考链保留策略等）；默认合理、高级可调；配置可持久化、可导出/复用，避免「黑盒运行时」 |
| **Grounded** | 文件/记忆类回答必须基于工具输出；**内容类问题未 `file_read`（或等价 MCP 读文件）不准回复**（仅 `list_dir` 不够） |
| **Harness-first** | 产品 harness（Turn · confirm · SSE · profiles）自研；LLM/Agents **库**基座为 vendor fork **aisuite**；**不用 LangGraph**；**不 fork / 不嵌入** Pi · Hermes · OpenCode · OpenWorker 产品 runtime |
| **Controlled tree** | 默认浅树（`depth=1`）；可配 **受控深树** `max_depth≤2`（硬顶 3）；并行与总节点有预算；禁止无限发散 |
| **Parent / referee decides** | 多路摘要由**项目主管**综合；可选 `verify` / `ask_user`；高分歧或高风险写路径可进入**结构化对抗**（方案主张 ↔ 风险质询，评审仲裁收束）；**禁止**子↔子自由总线与无限互撕 |
| **WriteGate** | 子 Agent 只写隔离草稿（proposals）；**项目落地**仅主管/仲裁收尾经确认后写入业务路径 |
| **Conversation map** | 线程内分支 / fork / rollback / restore 为已交付差异点；地图表达「任务怎么走过来」，不是组织协作平台 |
| **Skill orchestration (planned)** | Skill DAG 与对话地图**产品入口分离**（回顾路径 vs 设计流程） |
| **Integrations = MCP or CLI** | 外部能力只经标准 MCP 或 CLI；不新增平台专用 connector |
| **Knowledge optional** | 启用且就绪时，**每轮自动** Shibei 答前召回注入 system prompt；不足再 `shibei_search` |
| **Token-aware** | PromptGate / compaction / 子 Agent 只回摘要——省上下文、提高任务完成密度 |
| **Minimal UI** | 紧凑 Electron 桌面；双语 English · 中文 |

### 非目标（v0.3）

- 多用户 / 云端后端 / 移动优先（**不等于**不做企业友好能力：思考链审计、可配置 harness 仍做）
- 「个人秘书」人格产品叙事
- **以「Agent 协作平台 / 自由 Swarm / 聊天室式多智能体」为产品定位**
- **无限深度树、无预算并行、子↔子自由 peer 总线、无限互撕式辩论**（受控深树 depth≤2 与结构化对抗见规格，另述）
- 为各 SaaS（飞书/微信读书/小红书等）继续扩展一等公民自定义 Connector
- 无需确认的全自动 Agent
- LangGraph / **fork 或嵌入** Hermes·OpenCode·**Pi** · OpenWorker runtime（**例外：** 允许 vendor fork [aisuite](https://github.com/andrewyng/aisuite) 作为 LLM + Agents **库**基座，见 [2026-08-03-aisuite-base-design.md](superpowers/specs/2026-08-03-aisuite-base-design.md)；不以此替换 Electron 产品壳）
- IM 网关作为主 UI（FR-16 Deferred）
- Orchestrator 作为独立 Profile（已移除；委派能力并入 **Build**）
- 将 Skill DAG 未完成部分宣称为已上线
- 恢复 `spawn_cli_agent`（已 Removed）；CLI 指用户配置的 MCP stdio / shell，不是外接编码 Agent 委派
- 把「思考链」做成不可关闭的强制云端上报；默认本地留存，导出/分析由用户或企业管控环境决定

### 架构抉择：为何不 fork Pi 重写

| 选项 | 结论 |
|------|------|
| **Fork Pi 重写 Lumina** | **不做。** Pi 是 TypeScript 极简 coding loop；Lumina 是 Python harness + Electron 确认流 + 对话地图 + Shibei + MCP 产品层。Fork 等于丢弃已交付差异点，再重新实现一遍。 |
| **嵌入 Pi runtime** | **不做**（与 Hermes/OpenCode 同列非目标）。 |
| **可借鉴（非依赖）** | 短 system prompt、工具面克制、扩展点清晰——写进 prompt/工具设计纪律，不引入 Pi 代码。 |

详见 [harness-design.md](harness-design.md)。

### 委派模型（受控树 + 可选结构化对抗）

```
项目主管（Build / Root）
  ├── 调研分析 ×N（explore，只读，有并行上限）
  ├── 产品经理（plan，可再拆一层，仅 deep_tree）
  ├── 执行者（worker → 仅 proposals 草稿）
  ├── [可选] 结构化对抗
  │     方案主张 ←交替辩词→ 风险质询（默认≤6 轮，硬顶 12；仲裁可提前结束）
  │     → 评审仲裁 synthesize
  └── 项目落地（WriteGate.apply，需 confirm）

深度：默认 shallow=1；deep_tree 可配 ≤2（硬顶 3）
信道：父↔子；对抗为共享 transcript 交替发言（非 peer 总线）
禁止：无限深度、子直写业务路径、自由互撕房间
```

| 模式 | 是否做 | 说明 |
|------|--------|------|
| 单层委派 + 摘要回传 | **做**（已交付） | 降上下文、隔离工具权限 |
| 并行 explore | **做**（有上限） | 分头查资料/代码 |
| 一次 verify | **做**（archetype 已有） | 主管需要时派审查 |
| 人确认（confirm / ask_user） | **做** | 危险动作与关键歧义升给人 |
| 受控深树 depth≤2 | **规划**（FR-54） | 硬顶 3；仅 explore/plan 可再 spawn |
| 结构化对抗 + WriteGate | **规划**（FR-53/55） | auto/force/off；落地只经项目落地 |
| Mission Strip UI | **规划**（FR-56） | 岗位中文名 + 进度条 + 展开思考；对抗独立左右面板 |
| 自由 peer 辩论房间 / 无限互撕 | **不做** | 贵、吵、难控 |

---

## 2. Target User · 目标用户

**主要用户：** 需要本地可控 Agent 做开发与知识工作的个人用户（含「一人承担多角色」场景）——执行文件/Shell、对话分支探索、经 MCP/CLI 扩展工具；可选接入 Shibei 与记忆。Skill 工作流编排为后续差异化能力，面向同一用户群。

**企业运行语境（能力要求，非改定位）：** 当 Agent 进入企业可控环境（内网部署、合规抽检、事故复盘、质量评估）时，**思考链必须可记录 / 可追溯 / 可分析**，且 harness 行为应能通过**大量可定制参数**按团队策略收紧或放宽——产品仍本地优先、非多租户云 SaaS，但运行时可观测、可审计、可调参。

---

## 3. Agent Profiles · 主会话模式

> 权限通过**工具列表过滤**实现（OpenCode permission ruleset），不靠 prompt 许愿。

| Profile | 中文 | 用途 | 工具边界 |
|---------|------|------|----------|
| **auto** | 自动 | **默认**；系统按问题类型选 Ask/Plan/Build | 运行时解析为 ask/plan/build 之一 |
| **build** | 执行 | 读写、委派、MCP/CLI | 全工具 + `spawn_subagent` |
| **ask** | 问答 | 检索与只读分析 | 只读 FS/记忆/Shibei/联网/浏览器/MCP 只读/`ask_user` + **`code_exec`**（可读工作区、不可写回） |
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
| 文件系统 | **`ls`**（别名 `list_dir`）, **`read`**（别名 `file_read`）, **`grep`**（别名 `search_files`）, **`glob`**（别名 `glob_files`/`find`） | 读：否 | 列目录、读文件、rg 搜内容、glob 找文件（对齐 Pi） |
| 文件系统 | **`write`**（别名 `file_write`）, **`edit`**（别名 `patch`）, **`move`**, `file_delete` | 是* | 写/精确替换/移动/删（确认卡片对 write/edit 展示 diff 预览；`edit` 需唯一匹配） |
| 执行 | `shell` | 是* | 只读命令可免确认 |
| 执行 | **`code_exec`** | 是* | 沙箱跑 Python：可读工作区、禁写工作区、禁网；会话内首次确认后可免；Ask/Build 可用，Plan 不可 |
| 记忆 | `search_memory`, `session_search`, `memory` | 读：否 | Lumina SQLite + 会话记忆 + MD 写入 |
| Shibei | `shibei_search`, `shibei_import`, `shibei_list_sources` | 否 | 语义 KB（设置开启时注入） |
| 联网 | `web_search`, `web_fetch` | 否 | API：Tavily/Brave/博查 + Serper/SerpAPI/Bing/Perplexity 预留；HTML 降级 |
| 任务 | `todo`, `skills_list`, `skill_view` | 否 | 待办与技能（Skill **编排**见 F26） |
| 交互 | `clarify`, **`ask_user`** | 否 | 追问；`ask_user` 支持选项，前端可点选 |
| 委派 | `spawn_subagent` | 否 | 子 Agent（Build）；默认不可再 spawn；deep_tree 下仅 explore/plan 可再拆一层 |
| MCP | `mcp_{server}_{tool}` | 视工具 | **现行外部集成主路径**：stdio / SSE / Streamable HTTP |
| CLI | `shell`（及 MCP stdio 包装的 CLI） | shell：是* | **现行外部集成主路径**；非 `spawn_cli_agent` |
| 浏览器 | `browser_*` | 否 | 按需注入；含 **`browser_screenshot`**（`agent-browser` CLI） |
| ~~遗留 Sync~~ | ~~`list_connectors` / `sync_source`~~ | — | **Removed**（2026-08）；个人知识走 Shibei / MEMORY.md / MCP |

### 4.2 Sub-agent 工具集（默认 `depth=1`；deep_tree 见 FR-54）

| Archetype | 工具 |
|-----------|------|
| explore / verify / plan | 只读 FS + 记忆 + 联网；（deep_tree）explore/plan 可再 `spawn_subagent` 一层 |
| worker | 只读 + 写 **proposals 草稿** / `shell`（需确认）；**不直写业务路径**（WriteGate，FR-53） |
| pro / con / referee | 对抗角色（FR-55）；读写限于辩词与 proposals；落地仅 referee/root |
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
| Sub-agent pause/resume + 进度树（单层） | Done |
| `spawn_cli_agent` 核心 + 设置 UI | **Removed** |
| **`ask_user` 结构化追问 + UI 选项** | **Done** |
| Chat Markdown（markdown-it + DOMPurify） | Done |
| 多线程持久化（`/api/chat/threads`） | Done |
| **思考链轨迹**（可记录 · 可追溯 · 可分析；企业审计友好） | **Done（MVP）**（FR-51） |
| **Harness 可定制参数面**（确认 / 委派 / compaction / 轮次 / 超时 / 路由 / 轨迹保留等） | **Done（MVP）**（FR-52） |

### 5.2 Memory & Knowledge

| 能力 | 状态 |
|------|------|
| Shibei KB 直连 + workspace UI | Done |
| Shibei-first 读记忆路由 | Done |
| **Shibei 每轮自动答前召回**（`context` → system prompt） | **Done** |
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
用户任意消息（Shibei 已启用且就绪）
  → 构建 system prompt 时自动调用 Shibei.context（答前召回）
  → 注入「## Shibei 答前召回」；不足时 Agent 仍可 shibei_search
用户：「读取记忆：面试准备」
  → PromptGate LIGHT + 自动召回；可再 shibei_search → grounded 回复
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

**Sub-agent 确认（单层）**

```
spawn_subagent(worker) → file_write 需确认
  → UI 暂停 + 子 Agent 树 → Allow → resume → 摘要回父 Agent
（子 Agent 不可再 spawn）
```

**多路 explore 汇总（非辩论）**

```
主 Agent → spawn explore ×N（≤3）
  → 各路只回摘要
  → 主 Agent 综合；歧义大则 ask_user 或 spawn verify 一次
  → 再决定是否 spawn worker 落盘
```

---

## 7. System Architecture · 系统架构

```
┌──────────── Electron Desktop ────────────┐
│  chat · settings（含 harness 高级参数） │
│  Build/Ask/Plan · conversation map      │
│  思考链展开 / 轨迹切片 · workspace      │
│  SSE: /api/chat/progress/{trace_id}     │
└──────────────────┬───────────────────────┘
                   │ localhost:8765
┌──────────────────▼───────────────────────┐
│  ChatService                             │
│    → PromptGate → grounding / routing    │
│    → TurnRunner → AgentLoop              │
│    → ReasoningTrace（记录/追溯/导出）    │
│    → HarnessConfig（可定制参数面）       │
│    → spawn_subagent（depth≤1）           │
│  ChatToolRegistry (profile 过滤)         │
│  McpManager（标准 MCP = 外部集成主路径） │
│  Scheduler: briefing · think             │
│  Legacy: SyncService / connectors 冻结   │
└──────────┬─────────────┬─────────────────┘
           │             │
    ~/.lumina/      Shibei ~/.shibei/db
    agent · mcp     （可选读记忆）
    traces · harness config
```

**知识读取优先级：** 每轮自动 `Shibei.context`（启用且就绪时）→ 按需 `shibei_search` → `session_search` → `search_memory` → MEMORY.md  
**外部集成：** 标准 MCP 或 CLI（见 §1）；平台专用 Connector = Legacy frozen。  
**Runtime：** 自研 Python harness；不 fork / 不嵌入 Pi；思考链与可定制参数为一等公民（FR-51 / FR-52）。

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
| **FR-48** | **Shibei 每轮自动答前召回**（`context` 注入 system prompt） | **P1** | **Done** |
| FR-10 | 双语 UI | P1 | Done |
| FR-11 | 后台思考（Think） | P1 | Done |
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
| **FR-45** | **对话地图：节点角色/状态标注**（人 · 主 Agent · status；SSE 叠加 waiting_confirm / archetype） | **P2** | **Done** |
| **FR-46** | **委派与确认策略面板**（archetype 权限摘要 · 会话授权范围 · 深度限制说明） | **P2** | **Done** |
| **FR-47** | **Turn 效率可见**（compaction / 子 Agent 摘要 / 工具轮次等轻量指标） | **P2** | **Done** |
| **FR-49** | **工作流 HumanReview / confirm_before 暂停恢复** | **P2** | **Done** |
| **FR-50** | **工作流演示模板**（research / code_change） | **P2** | **Done** |
| **FR-51** | **思考链可记录 / 可追溯 / 可分析**（见下方说明） | **P1** | **Done（MVP）** |
| **FR-52** | **Harness 大量可定制参数**（见下方说明） | **P1** | **Done（MVP）** |

#### FR-51 · 思考链（Reasoning Trace）

对企业可控运行环境为一等公民能力。Agent 每一轮的决策过程应形成**结构化思考链 / 运行轨迹**，而非仅最终回复。  
（注：FR-49/50 已用于工作流 HumanReview / 演示模板，故思考链与 harness 参数使用 **FR-51 / FR-52**。）

| 维度 | 要求 |
|------|------|
| **可记录** | 持久化：模型 reasoning / 中间结论（若提供）、工具调用意图与结果摘要、确认与拒绝、子 Agent 委派与回传、compaction / profile 切换等关键节点；关联 `trace_id` · `turn_id` · `thread_id` |
| **可追溯** | 从对话地图 / Turn / 工具事件反向定位到完整轨迹；支持按会话、时间、工具名、确认结果过滤；跨重启可恢复（与 Turn 持久化对齐） |
| **可分析** | 导出结构化格式（如 JSONL）；支持事后复盘、失败归因、合规抽检、评测对照（可与 F23 eval harness 衔接）；可选轻量聚合指标（工具成功率、确认次数、委派深度占用） |
| **隐私默认** | 默认本地留存于 `~/.lumina/`；**不**默认云端上报；保留策略（全量 / 摘要 / 关闭）本身可配置（属 FR-52） |
| **与 UI 关系** | 聊天侧可按需展开思考过程；地图侧可点节点看轨迹切片；完整分析面可后置，但数据模型先到位 |

#### FR-52 · Harness 可定制参数面

Harness 不是固定黑盒：确认、委派、压缩、轮次、超时、路由、轨迹等行为应有**大量可调参数**，默认安全合理，高级用户 / 企业策略可细调。

| 参数族（示意，非穷尽） | 示例旋钮 |
|------------------------|----------|
| **确认策略** | 哪些工具需确认、会话内「始终允许」范围、超时、取消语义 |
| **委派与拓扑** | 并行 explore 上限、archetype 默认工具集、depth 说明（硬限仍为 1）、worker 隔离策略 |
| **循环与预算** | max tool rounds、light/full 步数、单 turn 超时、shell 超时 |
| **上下文** | compaction 触发阈值 / 保留窗口、子 Agent 摘要长度、PromptGate 开关与置信度 |
| **模型与路由** | profile 默认、Auto 规则敏感度、（Deferred）explore 便宜模型开关 |
| **思考链** | 全量 / 摘要 / 关闭；保留天数；是否含 raw reasoning |
| **知识与记忆** | Shibei 自动 context 开关、Background Review 开关 |
| **安全沙箱** | `code_exec` 确认记忆、工作区只读边界相关选项 |

**交付形态：** 配置落盘（如 `~/.lumina/agent.json` / harness 专段）+ 设置 UI 分层（常用 / 高级）+ 文档化参数表；与 FR-46 策略面板、FR-47 效率可见互补——面板解释「当前生效策略」，参数面负责「改策略」。

---

## 9. Naming: CLI vs CLI Agent

| 术语 | 含义 | 状态 |
|------|------|------|
| **CLI（现行）** | 用户经 `shell` 或 **MCP stdio** 调用的外部命令行工具 | 支持；外部集成主路径之一 |
| **`spawn_cli_agent` / FR-30** | 外接编码 Agent 委派（codex/kimi 等） | **Removed**（2026-07） |
| **委派 / sub-agent** | 主管 spawn 子任务；摘要回传；可选受控深树 | 支持；结构化对抗另见 FR-55 |
| **IDP（Internal Delegation Protocol）** | 委派信封 / 生命周期 / 信道 / 冲突策略的类型化协议 | **Done（MVP）**；将扩展辩论 transcript / WriteGate；见 specs |
| **Mission Strip** | 岗位化进度条（项目主管 / 调研分析 / …） | **规划**（FR-56）；非像素头像协作房 |
| **协作（偶用）** | 人与 Agent 共同推进任务（确认、追问、地图回看） | 文案可用；**不作**产品品类名 |

---

## 10. Success Metrics · 成功指标

| 指标 | 目标 | 当前 |
|------|------|------|
| 单元测试 | CI 全绿 | **~559** passed（随 CI） |
| 无 sync 读 Shibei | 零同步可问答 | Done |
| Ask 模式不误写 | Plan/Ask 无 shell/write | Done |
| 子 Agent 树深度 | 默认 depth=1；可配 ≤2（硬顶 3） | Done（浅树）；深树见 FR-54 |
| WriteGate | 子不可写业务路径；落地经确认 | 规划 FR-53 |
| 冷启动（不含 LLM） | <30s | Manual QA |
| 外部集成路径 | 仅 MCP / CLI | 原则已锁定；legacy connector 冻结 |
| 上下文效率（方向） | compaction / 摘要委派可观测（FR-47） | Done |
| 思考链完整性（方向） | 关键 turn 具备可导出结构化轨迹（FR-51） | **Done（MVP）** |
| Harness 可调参面（方向） | 确认/委派/compaction/轮次/轨迹等主要旋钮可配置且文档化（FR-52） | **Done（MVP）** |

---

## 11. Roadmap · 路线图

### Shipped · v0.1.x – v0.2.x（已交付）

- Shibei KB + workspace UI + Shibei-first 路由
- Sub-agent pause/resume + 进度树（**单层**）
- Harness P0（TurnRunner · SSE schema v2 · DelegationResult）
- **Build / Ask / Plan**（移除 Orchestrator）
- **P0 工具**：`glob_files` · `ask_user` · MCP；平台 connector 工具 → Legacy
- **Browser**：`browser_screenshot` · Ask/Plan 调研路由
- 多线程 API + UI、**分支地图**、动态标题、Markdown 聊天
- `code_exec` 工作区只读沙箱（Ask/Build）

---

### Next · v0.3 Harness 可见性与工作流（2026-07）

方向：把已有 harness **说清楚、看得见、可调参、可追溯**；加深人机共进与企业可控运行体验；在 WriteGate 约束下扩展**受控深树**与**结构化对抗**（非自由 Swarm）。详见 [controlled-tree design](superpowers/specs/2026-07-30-controlled-tree-adversarial-mission-strip-design.md)。

| # | 任务 | 状态 | FR |
|---|------|------|-----|
| **V1** | 对话地图节点角色/状态标注 | **Done** | FR-45 |
| **V2** | 委派与确认策略面板（设置/帮助） | **Done** | FR-46 |
| **V3** | Turn 效率轻量可见（compaction 等） | **Done** | FR-47 |
| **V4** | Skill DAG：HumanReview / confirm_before 暂停恢复 | **Done** | FR-49 / F26 |
| **V5** | 可演示工作流模板（research / code_change） | **Done** | FR-50 / F26 |
| **V6** | **思考链轨迹：记录 · 追溯 · 导出/分析**（企业运行友好） | **Done（MVP）** | FR-51 |
| **V7** | **Harness 可定制参数面系统化**（配置 + 设置 UI + 参数表） | **Done（MVP）** | FR-52 |
| **V8** | WriteGate + proposals 草稿隔离 | **Planned** | FR-53 |
| **V9** | 受控深树 depth 可配 ≤2（硬顶 3） | **Planned** | FR-54 |
| **V10** | 结构化对抗（auto/force/off，轮次 6/12，仲裁可提前结束） | **Planned** | FR-55 |
| **V11** | Mission Strip + 辩论独立 UI（岗位中文名 / 进度 / 展开思考） | **Planned** | FR-56 |

#### Paused / Deferred

| # | 任务 | 决策 |
|---|------|------|
| — | CLI provider 端到端（FR-30d） | **Removed** |
| — | Briefing/Think Shibei 优先 | **暂停** |
| — | `mode: primary` 自定义主 Agent | **不做**；用 Auto 替代 |
| — | FR-28 Explore 便宜模型 | **Deferred**（往后放；值得做，非辩论） |
| — | FR-27 打包内嵌 Python | **Deferred** |
| — | FR-16 IM 网关 | **Deferred** |
| — | FR-37 Git 只读工具 | **Deferred** |
| — | **自由 peer 辩论房间 / 无限互撕 swarm** | **明确不做**（结构化对抗走 FR-55） |
| — | **Fork Pi 重写** | **明确不做** |

#### Later · 平台（P2–P3）

| # | 任务 | FR |
|---|------|-----|
| N11 | 打包内嵌 Python | FR-27（Deferred） |
| N13 | 定时 Agent / cron | Backlog |
| N14 | IM 网关（飞书 bot） | FR-16（Deferred） |

#### Future · 差异化与 Agent 演进（P3 / Research）

| # | 任务 | 说明 |
|---|------|------|
| **F26** | **Skill 编排（工作流 DAG）** | **Done（MVP+）**：画布 + HumanReview/confirm_before + 演示模板；AgentNode 支持 `mode=llm`（默认）与 `mode=agent`（TurnRunner/AgentLoop，工具确认经 pause/resume，无 spawn） |
| F20 | **Skill 自进化** | 基于反馈或失败更新 SKILL.md / run.py |
| F21 | **反思记忆（Reflexion-style）** | **Done（MVP）**：失败 turn → reflect → episodes → top-3 注入 |
| F22 | **代码级自修复** | 显式确认下改自身源码并跑测；默认关闭 |
| F23 | **评测 harness（eval-driven）** | **Done（MVP）**：`tests/eval` |
| F24 | **智能 archetype 选择** | **Done（MVP）** |
| F25 | **结构化输出卡片** | **Done（MVP）** |

### 明确不做（近期）

- LangGraph 迁移
- **Fork / 嵌入 Pi、Hermes、OpenCode runtime**
- **自由 peer 辩论房间、无限深度 / 无预算 swarm、子 Agent 直写业务路径**
- Orchestrator 第三种 Profile 回归
- CLI provider / `spawn_cli_agent`（FR-30 已 Removed）
- 为飞书/读书等 SaaS **新增或扩展**平台专用 Connector
- `~/.lumina/subagents/*.md` 的 `mode: primary` 第四种主 Agent
- 恢复桌面定位（改由 MCP/定时任务覆盖）
- 将 Skill 编排（F26）未完成部分宣称为已上线
- 以「Agent 协作平台 / 聊天室式多智能体」重定位产品
- 像素头像 + 拟人昵称式 Agent 人设 UI（Mission Strip 用岗位名）

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
| 思考链轨迹（FR-51） | `trace_store.py` · `deps.build_progress_callback` · `/api/chat/traces/*` |
| Harness 参数（FR-52） | `harness_config.py` · `agent.json` → `harness` · 设置 `agent_harness` |
| Context compaction | `context_compaction.py` |
| 反思记忆 | `src/secretary/agent/reflection/` |
| Auto profile | `agent_profile.py` · `effective_profile()` |
| Chat UI | `desktop/ui/chat.js` · `chat.css` |
| Harness 设计 | [harness-design.md](harness-design.md) |
| Skill DAG | [workflow-dag-design.md](workflow-dag-design.md) |
| 受控深树 / 对抗 / Mission Strip | [superpowers/specs/2026-07-30-controlled-tree-adversarial-mission-strip-design.md](superpowers/specs/2026-07-30-controlled-tree-adversarial-mission-strip-design.md) |

---

## 13. Open Decisions · 待决

| 话题 | 决策 |
|------|------|
| 读记忆默认 | Shibei 启用且就绪时**每轮自动 context**；不足再 `shibei_search`；miss 再 `search_memory` |
| 外部集成 | **只做标准 MCP 或 CLI**；不新增平台专用 Connector |
| Sync / 自定义 connectors | **遗留冻结** |
| CLI vs sub-agent | **`spawn_cli_agent` 已删除**；CLI = MCP stdio / `shell` |
| 主 Agent 扩展 | **Auto** 替代 `mode: primary` |
| Runtime 底座 | **自研 Python harness**；不 fork Pi |
| 子 Agent 拓扑 | 默认 **depth=1**；可配深树 ≤2（硬顶 3）；并行有预算 |
| 对抗 / 落地 | 结构化对抗可选；WriteGate；见 FR-53–56 与 2026-07-30 规格 |
| 歧义处理 | 主管综合 → `ask_user` / `verify` / 评审仲裁 |
| Web search | **Done** |
| Briefing/Think | 暂停；先 harness 可见性 |
| Background Review | 活跃 |
| 打包 Python | v0.2 spike：sidecar venv |
| FR-45–50 / F26 v0.3 Next | **全部 Done**（Deferred 项仍除外：IM/内嵌 Python/Explore 便宜模型等） |
| 思考链（FR-51） | **做**：可记录 / 可追溯 / 可分析；默认本地；企业审计与复盘为一等场景 |
| Harness 可定制参数（FR-52） | **做**：大量旋钮系统化暴露；默认合理、高级可调；与 FR-46/47/51 联动 |
| 企业能力边界 | 做可观测与可调参；**不做**多租户云后端（仍属非目标） |

---

*End of document · 文档结束 · v0.3.1*
