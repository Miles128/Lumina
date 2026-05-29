# Lumina · 灵犀 — Product Requirements Document

**Version:** 0.1.0  
**Author:** 四海 (myx28@qq.com)  
**Last updated:** 2026-05-30  
**Status:** Active development

---

## 1. Product Vision · 产品愿景

### English

Lumina is a **local-first personal AI secretary** for a single user. It runs on the user's machine, connects to OpenAI-compatible LLMs, and acts as a persistent assistant that knows the user's context through synced data sources, durable memory, and tool use — without turning into a generic chatbot.

Design principles:

- **Local & private** — data stays on device by default (`~/.lumina/`)
- **Action-oriented** — the agent reads files, runs commands, searches memory, and fetches the web; risky actions require explicit confirmation
- **Transparent** — tool progress and streaming replies are visible; no fake “thinking” filler or robotic timing messages
- **Minimal UI** — dense, space-efficient desktop chat; bilingual labels (English · 中文) by default
- **Hermes-compatible** — reuses LLM config, SOUL, MCP servers, and memory patterns from Hermes where useful

### 中文

灵犀（Lumina）是一款**本地优先的个人 AI 秘书**，面向单一用户。应用在用户本机运行，接入 OpenAI 兼容大模型，通过数据源同步、持久记忆和工具调用持续理解用户上下文，而不是退化成通用聊天机器人。

设计原则：

- **本地与隐私** — 数据默认留在本机（`~/.lumina/`）
- **能干活** — Agent 可读文件、执行命令、搜记忆、联网；高风险操作必须经用户确认
- **过程可见** — 工具进度与流式回复对用户可见；不展示无意义的耗时提示或套话
- **界面克制** — 桌面聊天界面紧凑；标签默认双语（先英后中）
- **兼容 Hermes** — 在合适处复用 Hermes 的 LLM、SOUL、MCP 与记忆模式

---

## 2. Target User · 目标用户

### English

**Primary:** The developer / owner (四海) — a power user who wants one desktop app to:

- Ask questions about their own data (reading habits, schedule, profile, files)
- Delegate file search, shell commands, and light automation with guardrails
- Accumulate long-term memory across sessions without manual note-taking

**Not targeting (v0.1):** teams, multi-tenant SaaS, mobile-first users, or users who need fully autonomous agents without confirmation.

### 中文

**主要用户：** 开发者 / 产品拥有者（四海）—— 希望用一款桌面应用：

- 基于个人数据提问（在读什么、日程、画像、文件等）
- 在可控前提下委派文件检索、Shell 命令与轻量自动化
- 跨会话积累长期记忆，无需手工维护笔记

**非目标（v0.1）：** 团队协作用户、多租户 SaaS、移动优先用户、以及无需确认的全自动 Agent 场景。

---

## 3. Problem Statement · 问题陈述

### English

| Pain | Lumina response |
|------|-----------------|
| ChatGPT / web UIs don't know my local files or Feishu/Xiaohongshu data | Connectors + profile sync + memory search |
| CLI agents (Hermes, OpenClaw) are powerful but lack a polished daily driver UI | Electron chat + settings + skills panel |
| Agents run dangerous commands silently | Confirmation flow for shell / write / delete |
| Long tasks feel like a black box | SSE progress log + streaming final reply |
| Memory scattered across apps | MEMORY.md / USER.md + background review + daily summary |

### 中文

| 痛点 | 灵犀的回应 |
|------|-----------|
| 网页 ChatGPT 不了解本地文件和飞书 / 小红书等数据 | 连接器 + 画像同步 + 记忆检索 |
| CLI Agent 能力强但缺少日常可用的桌面 UI | Electron 聊天 + 设置 + 技能面板 |
| Agent 静默执行危险命令 | Shell / 写入 / 删除需用户确认 |
| 长任务像黑盒 | SSE 进度日志 + 流式最终回复 |
| 记忆分散在各处 | MEMORY.md / USER.md + 对话后整理 + 每日摘要 |

---

## 4. Product Scope (v0.1) · 产品范围（v0.1）

### English

#### 4.1 Chat & Agent

- Multi-turn agent loop (up to 8 steps full mode, 3 steps light mode)
- Tools: list/read/write/patch/delete files, shell, search files, search memory, session search, web search/fetch, memory mutate, todo, skills list/view, clarify
- MCP tools bridged as `mcp_{server}_{tool}` (stdio transport)
- Prompt gate: route sync / profile / direct / light / full agent / reject
- User confirmation for shell and file mutations; read-only shell whitelist for safe commands
- Streaming LLM tokens for direct replies and final agent replies (via SSE `reply_delta`)
- Pause in-flight requests; client-side timeout with clear error copy
- Thread list with local persistence (`localStorage`); restore last thread on launch

#### 4.2 Memory & Profile

- SQLite memory store + FTS search
- Hermes-style durable memory: `MEMORY.md`, `USER.md` (editable in Settings)
- Post-turn background review (LLM decides memory mutations)
- Scheduled think (default every 6h): reflect on recent sessions and update memory
- Daily memory summary (default 23:00): compress recent chats into MEMORY.md «Session Summary» section
- User profile: auto summary from synced sources + manual override
- Episode logging when tools are used

#### 4.3 Data Sources & Sync

- Platform settings UI for: Feishu, WeRead, Xiaohongshu, IMAP email, WeChat OA URLs, cloud drive paths, local documents
- Manual sync (top bar) + background auto-sync (configurable interval)
- Daily briefing generation (configurable hour)

#### 4.4 Skills & Knowledge

- Skill manager: catalog, install/uninstall, categories, card/table views, detail modal
- Executable skills mounted into agent context
- Knowledge workspace: note tree, graph view, rebuild index (legacy workspace route)

#### 4.5 Settings & UI

- Settings sheet: LLM, SOUL, durable memory, MCP, appearance, data sources, profile
- Appearance: density, message width, **language** (`en` | `zh` | `bi` default)
- Bilingual UI via `i18n.js` — labels format `English · 中文` in bilingual mode
- User avatar label: **Me · 我**; bot: **Lumina · 灵犀**
- About panel: developer, email, version
- Token usage counter (cumulative, from API usage or estimate)

#### 4.6 MCP

- Config file: `~/.lumina/mcp.json`
- Optional merge from `~/.hermes/config.yaml` (`import_hermes`)
- Settings UI: add server, import from Hermes, reload connection, tool list
- API: status, reload, CRUD servers, import-hermes

### 中文

#### 4.1 对话与 Agent

- 多轮 Agent 循环（完整模式最多 8 步，轻量模式 3 步）
- 工具：目录/读/写/补丁/删文件、Shell、搜文件、搜记忆、搜会话、联网搜/抓取、改记忆、待办、技能列表/查看、澄清
- MCP 工具桥接为 `mcp_{server}_{tool}`（stdio 传输）
- Prompt 路由：同步 / 画像 / 直答 / 轻量 / 完整 Agent / 拒绝
- Shell 与文件变更需确认；只读 Shell 白名单可免确认
- 直答与 Agent 最终回复支持流式 token（SSE `reply_delta`）
- 可暂停进行中的请求；客户端超时并有明确提示
- 对话线程列表本地持久化；启动时恢复上次线程

#### 4.2 记忆与画像

- SQLite 记忆库 + 全文检索
- Hermes 式持久记忆：`MEMORY.md`、`USER.md`（可在设置中编辑）
- 对话结束后台整理（LLM 决定是否更新记忆）
- 定时 Think（默认每 6 小时）：回顾近期会话并更新记忆
- 每日记忆摘要（默认 23:00）：将近期对话压缩写入 MEMORY.md「会话摘要」段
- 用户画像：同步源自动摘要 + 手动编辑
- 使用工具时记录 Episode

#### 4.3 数据源与同步

- 设置页配置：飞书、微信读书、小红书、IMAP 邮箱、公众号 URL、云盘路径、本地文档
- 手动同步（顶栏）+ 后台自动同步（可配置间隔）
- 每日简报（可配置小时）

#### 4.4 技能与知识库

- 技能管理：目录、安装/卸载、分类、卡片/表格视图、详情弹窗
- 可执行技能注入 Agent 上下文
- 知识库工作区：笔记树、图谱、重建索引（legacy 路由）

#### 4.5 设置与界面

- 设置面板：大模型、SOUL、持久记忆、MCP、界面、数据源、个人画像
- 界面：密度、消息宽度、**语言**（`en` | `zh` | `bi`，默认双语）
- 双语 UI（`i18n.js`）— 双语模式下标签为 `English · 中文`
- 用户头像：**Me · 我**；灵犀：**Lumina · 灵犀**
- 关于：开发者、邮箱、版本
- Token 累计计数

#### 4.6 MCP

- 配置文件：`~/.lumina/mcp.json`
- 可选合并 `~/.hermes/config.yaml`
- 设置 UI：添加服务器、从 Hermes 导入、重新连接、工具列表
- API：状态、重载、增删改服务器、导入 Hermes

---

## 5. User Flows · 用户流程

### English

#### 5.1 First run

1. Install Python deps + Electron  
2. Configure LLM in Settings → LLM (or `.env` / Hermes import)  
3. Start backend + desktop  
4. Optional: configure data sources → Sync  
5. Chat with suggested prompts on welcome screen  

#### 5.2 Agent task with confirmation

1. User sends task (e.g. find resume files)  
2. Agent proposes shell command → confirmation bubble  
3. User taps Allow / Deny (or session write grant for new files)  
4. Tool runs in user home (or configured `shell_working_dir`)  
5. Real output returned; progress visible in SSE log  
6. Reply streams token-by-token when model generates final answer  

#### 5.3 Add MCP server

1. Settings → MCP Tools  
2. Enter name, command, args → Save & Connect  
   **or** Import from Hermes → Reload  
3. Tools appear in catalog; agent can call on next chat  

### 中文

#### 5.1 首次使用

1. 安装 Python 依赖与 Electron  
2. 在设置 → 大模型 配置 LLM（或 `.env` / 从 Hermes 导入）  
3. 启动后端与桌面端  
4. 可选：配置数据源 → 同步  
5. 在欢迎页使用推荐问题开始对话  

#### 5.2 需确认的 Agent 任务

1. 用户发送任务（如查找简历文件）  
2. Agent 提议 Shell 命令 → 确认气泡  
3. 用户允许 / 拒绝（新建文件可「本次授权」）  
4. 在用户主目录（或配置的 `shell_working_dir`）执行  
5. 返回真实输出；SSE 日志可见进度  
6. 最终回复流式输出  

#### 5.3 添加 MCP 服务器

1. 设置 → MCP 工具  
2. 填写名称、命令、参数 → 保存并连接  
   **或** 从 Hermes 导入 → 重新连接  
3. 工具出现在列表；下次对话 Agent 可调用  

---

## 6. Non-Goals (v0.1) · 非目标（v0.1）

### English

- Multi-user accounts or cloud-hosted backend
- Native mobile apps
- MCP HTTP/SSE transport (stdio only today)
- Sub-agent parallelization or cron-defined agent jobs
- IM channel gateway (WeChat/Feishu bot as primary UI)
- Fully autonomous shell/file ops without confirmation
- Token-level streaming inside tool execution output

### 中文

- 多用户账号或云端托管后端
- 原生移动 App
- MCP HTTP/SSE 传输（当前仅 stdio）
- 子 Agent 并行或 Cron 定时 Agent 任务
- 以 IM 通道（微信/飞书机器人）为主界面
- 无需确认的全自动 Shell/文件操作
- 工具执行过程中的输出级流式传输

---

## 7. System Architecture · 系统架构

### English

```
┌──────────────── Electron Desktop ────────────────┐
│  index.html · chat.js · settings.js · i18n.js    │
│  SSE: /api/chat/progress/{trace_id}              │
│  REST: /api/chat · /api/chat/confirm             │
└────────────────────┬─────────────────────────────┘
                     │ localhost:8765
┌────────────────────▼─────────────────────────────┐
│  FastAPI (secretary.api.app)                     │
│  ChatService → PromptGate → TurnOrchestrator     │
│              → AgentLoop → Tools + MCP           │
│  BackgroundScheduler: sync · briefing · think    │
│                      · memory summary            │
└────────────────────┬─────────────────────────────┘
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
 ~/.lumina/    OpenAI-compat     External MCP
 memory.db     LLM API           (stdio)
 agent.json
 mcp.json
 MEMORY.md
```

**Key paths**

| Path | Purpose |
|------|---------|
| `~/.lumina/memory.db` | Synced chunks + FTS |
| `~/.lumina/agent.json` | LLM provider config |
| `~/.lumina/mcp.json` | MCP server definitions |
| `~/.lumina/MEMORY.md` | Durable facts |
| `~/.lumina/USER.md` | User preferences |
| `~/.lumina/platforms.json` | Connector credentials |

### 中文

```
┌──────────────── Electron 桌面端 ────────────────┐
│  index.html · chat.js · settings.js · i18n.js    │
│  SSE：/api/chat/progress/{trace_id}              │
│  REST：/api/chat · /api/chat/confirm             │
└────────────────────┬─────────────────────────────┘
                     │ localhost:8765
┌────────────────────▼─────────────────────────────┐
│  FastAPI (secretary.api.app)                     │
│  ChatService → PromptGate → TurnOrchestrator     │
│              → AgentLoop → 工具 + MCP            │
│  BackgroundScheduler：同步 · 简报 · Think        │
│                      · 记忆摘要                  │
└────────────────────┬─────────────────────────────┘
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
 ~/.lumina/    OpenAI 兼容 API    外部 MCP
 memory.db                      (stdio)
 agent.json
 mcp.json
 MEMORY.md
```

---

## 8. Functional Requirements · 功能需求

### English

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | User can chat with agent and receive streamed replies | P0 | Done |
| FR-02 | Shell/write/delete require explicit confirmation | P0 | Done |
| FR-03 | Read file/list dir without confirmation | P0 | Done |
| FR-04 | Tool progress visible via SSE | P0 | Done |
| FR-05 | Pause and timeout handling in UI | P0 | Done |
| FR-06 | Sync configured data sources into memory | P0 | Done |
| FR-07 | Edit profile and durable memory in Settings | P0 | Done |
| FR-08 | Install/manage skills from UI | P0 | Done |
| FR-09 | Add/reload MCP servers from Settings | P0 | Done |
| FR-10 | Bilingual UI with language setting | P1 | Done |
| FR-11 | Background think + daily memory summary | P1 | Done |
| FR-12 | Thread list with persistence | P1 | Done |
| FR-13 | Hermes LLM/SOUL/MCP import | P1 | Done |
| FR-14 | Sub-agents / parallel tasks | P2 | Planned |
| FR-15 | MCP HTTP transport | P2 | Planned |
| FR-16 | IM channel integration | P3 | Backlog |

### 中文

| ID | 需求 | 优先级 | 状态 |
|----|------|--------|------|
| FR-01 | 用户可与 Agent 对话并收到流式回复 | P0 | 已完成 |
| FR-02 | Shell/写入/删除需明确确认 | P0 | 已完成 |
| FR-03 | 读文件/列目录免确认 | P0 | 已完成 |
| FR-04 | 通过 SSE 展示工具进度 | P0 | 已完成 |
| FR-05 | UI 支持暂停与超时处理 | P0 | 已完成 |
| FR-06 | 将配置的数据源同步进记忆库 | P0 | 已完成 |
| FR-07 | 在设置中编辑画像与持久记忆 | P0 | 已完成 |
| FR-08 | 从 UI 安装/管理技能 | P0 | 已完成 |
| FR-09 | 在设置中添加/重载 MCP | P0 | 已完成 |
| FR-10 | 双语界面与语言设置 | P1 | 已完成 |
| FR-11 | 后台 Think + 每日记忆摘要 | P1 | 已完成 |
| FR-12 | 对话线程列表持久化 | P1 | 已完成 |
| FR-13 | 从 Hermes 导入 LLM/SOUL/MCP | P1 | 已完成 |
| FR-14 | 子 Agent / 并行任务 | P2 | 规划中 |
| FR-15 | MCP HTTP 传输 | P2 | 规划中 |
| FR-16 | IM 通道集成 | P3 |  backlog |

---

## 9. UX & Content Guidelines · 体验与文案规范

### English

- No automatic “request took X seconds” messages after replies  
- No generic opening phrases (“I'll help you with that”) — sanitized by `reply_safety`  
- Bot replies extend rightward but stop before user avatar column (~2em gap)  
- Labels in bilingual mode: **`English · 中文`** (English first)  
- User identity in chat: **`Me · 我`**  
- Assistant identity: **`Lumina · 灵犀`**  
- Error messages must be actionable (timeout → suggest narrowing scope)  

### 中文

- 回复后不得自动展示「耗时 X 秒」类文案  
- 禁止空洞开场白（如「我会认真帮你处理」）— 由 `reply_safety` 过滤  
- 回复区域向右加宽，但不越过用户头像列（约 2em 间距）  
- 双语模式标签：**`English · 中文`**（英文在前）  
- 用户身份：**`Me · 我`**  
- 助手身份：**`Lumina · 灵犀`**  
- 错误提示须可行动（超时 → 建议缩小范围）  

---

## 10. Security & Privacy · 安全与隐私

### English

- All runtime data under `~/.lumina/` by default; no telemetry in v0.1  
- Secrets via env vars / platform config — never committed to git  
- Shell runs with user permissions in configured working directory  
- Write/delete always confirm; session-scoped grant for **new file** creation only  
- MCP servers are user-supplied processes — treated as trusted by user choice  

### 中文

- 运行时数据默认在 `~/.lumina/`；v0.1 无遥测  
- 密钥通过环境变量 / 平台配置注入 — 不入库  
- Shell 在配置的工作目录下以用户权限执行  
- 写入/删除始终确认；**新建文件**可会话级授权  
- MCP 服务器为用户自行添加的进程 — 视为用户信任范围  

---

## 11. Success Metrics · 成功指标

### English

| Metric | Target (personal use) |
|--------|------------------------|
| Agent task completion (with confirm) | >90% return useful output |
| Test suite | 139+ tests passing |
| Cold start to first reply | <30s (excl. LLM latency) |
| Sync freshness | Auto-sync every 20 min default |
| Memory recall | Relevant hits in top 5 for profile questions |

### 中文

| 指标 | 目标（个人使用） |
|------|----------------|
| Agent 任务完成（含确认） | >90% 返回有用结果 |
| 测试套件 | 139+ 用例通过 |
| 冷启动到首次回复 | <30s（不含模型延迟） |
| 同步新鲜度 | 默认每 20 分钟自动同步 |
| 记忆召回 | 画像类问题 Top 5 命中相关片段 |

---

## 12. Roadmap · 路线图

### English

**P0 — Stability & visibility (ongoing)**  
- Harden shell edge cases; expand tests  
- Richer progress UI (tool args/output snippets)  
- Single unified SSE stream for progress + tokens  

**P1 — Capability**  
- Sub-agent delegation for complex tasks  
- Cron / scheduled agent jobs  
- MCP HTTP transport  
- Configurable `shell_working_dir` in Settings UI  

**P2 — Reach**  
- IM gateways (Feishu / WeChat) as optional channels  
- Plugin marketplace for connectors  
- Voice input / mascot mode polish  

### 中文

**P0 — 稳定性与可见性（持续）**  
- 加强 Shell 边界情况与测试  
- 更丰富的进度 UI（工具参数/输出片段）  
- 进度与 token 统一 SSE 通道  

**P1 — 能力扩展**  
- 复杂任务子 Agent 委派  
- Cron / 定时 Agent 任务  
- MCP HTTP 传输  
- 设置 UI 可配 `shell_working_dir`  

**P2 — 触达**  
- IM 网关（飞书 / 微信）作为可选通道  
- 连接器插件市场  
- 语音输入 / 吉祥物模式完善  

---

## 13. Open Questions · 待决问题

### English

1. Should default language follow system locale or stay `bi`?  
2. Should thread history sync to backend session DB for cross-device?  
3. When to promote workspace/knowledge UI vs. chat-only default?  
4. Public release vs. remain private personal tool?  

### 中文

1. 默认语言应跟随系统 locale 还是保持 `bi`？  
2. 线程历史是否应同步到后端会话库以支持跨设备？  
3. 何时主推知识库工作区 vs. 仅聊天默认入口？  
4. 是否公开发行，还是保持私人工具？  

---

## 14. References · 参考

### English

- Repository: https://github.com/Miles128/Lumina  
- README: `/README.md`  
- Config: `src/secretary/config.py`  
- Agent loop: `src/secretary/agent/loop.py`  
- Desktop UI: `desktop/ui/`  

### 中文

- 代码仓库：https://github.com/Miles128/Lumina  
- README：`/README.md`  
- 配置：`src/secretary/config.py`  
- Agent 循环：`src/secretary/agent/loop.py`  
- 桌面 UI：`desktop/ui/`  

---

*End of document · 文档结束*
