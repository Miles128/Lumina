# Lumina · 灵犀 — Product Requirements Document

**Version:** 0.2.0-draft  
**Author:** 四海 (myx28@qq.com)  
**Last updated:** 2026-05-30  
**Status:** v0.1.1 shipped · `feat/logo-subagent-grounding` 合入前 · v0.2 规划

<p align="center">
  <img src="assets/logo.png" alt="Lumina logo" width="96" />
</p>

---

## 1. Product Vision · 产品愿景

### English

Lumina is a **local-first personal AI secretary** for a single user. It runs on the user's machine, connects to OpenAI-compatible LLMs, and acts as a persistent assistant that knows the user's context through **Shibei semantic KB**, Lumina durable memory, optional connector sync, and tool use — without turning into a generic chatbot.

Design principles:

- **Local & private** — data stays on device by default (`~/.lumina/`, Shibei `~/.shibei/db`)
- **Action-oriented** — reads files, runs commands, searches knowledge, fetches the web; risky actions require explicit confirmation
- **Transparent** — tool progress, sub-agent tree, and streaming replies are visible
- **Grounded** — filesystem and personal-memory answers must be backed by tool output (`list_dir` / `file_read` / `shibei_search` / `search_memory`, etc.)
- **Shibei-first memory read** — personal notes/docs via Shibei KB; connector sync is **optional fallback**
- **Minimal UI** — dense Electron desktop chat; bilingual labels (English · 中文)
- **Harness-first sub-agents** — `spawn_subagent` with pause/resume; no LangGraph

### 中文

灵犀（Lumina）是一款**本地优先的个人 AI 秘书**，面向单一用户。应用在用户本机运行，接入 OpenAI 兼容大模型，通过 **Shibei 知识库**、持久记忆、可选数据源同步和工具调用持续理解用户上下文。

设计原则：

- **本地与隐私** — 数据默认留在本机
- **能干活** — 可读文件、执行命令、检索知识库、联网；高风险操作必须确认
- **过程可见** — 工具进度、子 Agent 树、流式回复对用户可见
- **有依据** — 文件与记忆类回答必须基于工具结果
- **读记忆走 Shibei** — 个人文档优先 `shibei_search`；Lumina「同步」是备选
- **界面克制** — 紧凑桌面聊天；双语标签
- **Harness 式子 Agent** — 委派、暂停/恢复；不使用 LangGraph

---

## 2. Brand · 品牌

| Asset · 资源 | Path · 路径 | Usage · 用途 |
|--------------|-------------|--------------|
| Logo | `docs/assets/logo.png`, `desktop/ui/logo.png` | README, favicon, top bar, bot avatar, About |
| macOS app icon | `desktop/icons/icon.icns` | Packaged app **灵犀** |
| Product name | **Lumina · 灵犀** | UI, docs, `electron-builder` |
| User label | **Me · 我** | Chat avatar |
| Assistant label | **Lumina · 灵犀** | Chat / About |

**Status:** Done

---

## 3. Target User · 目标用户

**Primary · 主要用户：** 产品拥有者（四海）— 基于 Shibei 索引的个人笔记/文档提问、在可控前提下委派文件/Shell 任务、跨会话积累 Lumina 记忆。

**Not targeting (v0.2) · 非目标：** 团队、多租户 SaaS、移动优先、无需确认的全自动 Agent。

---

## 4. Product Scope · 产品范围

### 4.1 Chat & Agent · 对话与 Agent

| Capability · 能力 | Detail · 说明 | Status |
|-------------------|---------------|--------|
| Agent loop | Full 8 steps / light 3–4 steps | Done |
| Tools | FS, memory, web, MCP, Shibei, todo, skills, clarify | Done |
| Sub-agents | `explore` / `worker` / `verify` / custom md; parallel explore ≤3; depth=1 | Done |
| **Sub-agent pause/resume** | Shell/write 确认后子任务续跑；父 loop 一层 turn stack | **Done** |
| **Sub-agent progress tree** | `#agent-progress` 树形 UI | **Done** |
| Agent profiles | `build` / `plan` / `orchestrator` | Done |
| Prompt gate | Rules-first; optional LLM (`PROMPT_GATE_ENABLED`) | Done |
| Web & weather | `resolve_web_search` + geolocation | Done |
| Confirmation | Shell, write/patch/delete; read-only tools skip confirm | Done |
| Streaming | SSE: `reply_delta`, tool progress, sub-agent events | Done |
| Grounding | Forced read; MCP parsing; verified/unverified badge | Done (tuning) |
| **Chat Markdown** | `markdown-it` + DOMPurify（替换自写 parser） | **Done** (待合入) |
| Chat routing | All turns via `/api/chat` | Done |

### 4.2 Memory & Knowledge · 记忆与知识

| Capability · 能力 | Detail · 说明 | Status |
|-------------------|---------------|--------|
| **Shibei KB（主路径）** | 直连 Shibei `config.yaml` + `~/.shibei/db`；`shibei_search` / `import` / `list_sources` | **Done** |
| **KB 浏览 UI** | `workspace.html`：源列表、搜索、预览（替代 mascot 窗口） | **Done** |
| **读记忆路由** | Shibei 就绪时不拦截；LIGHT 模式优先 `shibei_search` | **Done** |
| **写记忆路由** | `写入记忆` 不被 sync_empty 误拦 | **Done** |
| Lumina `MEMORY.md` / `USER.md` | `memory` 工具 + 设置编辑 | Done |
| SQLite + FTS | 连接器同步后的 chunk 索引（**备选**） | Done |
| Legacy Lumina workspace | 旧 `/api/kb/*` 与 workspace export 仅保留手动兼容；不再随 sync 默认导出 | Legacy |
| Profile | 用户层 / 自动层 / chat facts 分离；保存不丢编辑 | Done |
| Background review | 仅持久化用户陈述事实 | Done |
| Scheduled think + daily summary | APScheduler | Done |

### 4.3 Data Sources & Sync · 数据源与同步（备选）

- Connectors: Feishu, WeRead, Xiaohongshu, IMAP, WeChat OA, cloud drive, local documents
- Manual + scheduled sync; daily briefing
- **定位变更：** 同步写入 Lumina SQLite，供 `search_memory` 与简报；**不是**读个人文档的前置条件
- Shibei `auto_import_on_sync`：同步后可增量导入 Shibei（可选）

**Status:** Done (connector reliability = ongoing ops)

### 4.4 Skills · 技能

- Skill manager UI; executable skills

**Status:** Done

### 4.5 Settings & Desktop UI · 设置与桌面

- LLM, SOUL, memory, MCP, **Shibei**, appearance, data sources, profile, About
- Language: `en` | `zh` | `bi`
- Pause / timeout; agent progress + sub-agent tree
- Grounding verified / unverified labels
- Clear chat history; clear polluted memory

**Status:** Done

### 4.6 MCP · MCP 集成

- `~/.lumina/mcp.json`; Hermes import; **stdio** transport
- MCP read tools count toward grounding

**Status:** Done (stdio). **HTTP/SSE:** Planned (FR-15)

### 4.7 Packaging & CI · 打包与 CI

| Item | Detail | Status |
|------|--------|--------|
| CI | pytest 3.11 + 3.12; ruff; mypy | Done |
| E2E smoke | `scripts/e2e-smoke.sh` (API + Playwright) | Done |
| macOS pack | `npm run pack` → **灵犀** `.dmg` | Done |
| Bundled Python | Packaged app still needs local Python + pip | Known limitation |

---

## 5. User Flows · 用户流程

**First run · 首次使用**

1. `pip install -e ".[dev]"` + `cd desktop && npm install`
2. 配置 LLM（`.env` 或 `~/.lumina/agent.json`）
3. **设置 → Shibei 知识库**：填写 Shibei 安装路径（默认 `~/Documents/Projects/shibei`）
4. `cd desktop && npm start` → 后端 `:8765`
5. 可选：设置 → 平台 → 连接器 + 「同步」（备选）
6. 聊天 / 知识库页检索个人文档

**Read memory · 读记忆（推荐）**

```
用户：「读取记忆：面试准备」
  → PromptGate LIGHT
  → shibei_search（Shibei ~/.shibei/db）
  →  grounded 回复
（无需先点「同步」）
```

**Write memory · 写记忆**

```
用户：「写入记忆：偏好简洁回复」
  → full agent
  → memory tool → USER.md / MEMORY.md
```

**Connector-specific · 连接器专项（备选）**

```
用户：「微信读书最近在读什么」
  → 优先 shibei_search（笔记里可能有书单）
  → 若无结果且 Lumina 已同步 WeRead → search_memory
  → 若皆无 → 提示配置 Shibei 或「同步」
```

**Sub-agent with confirmation · 子 Agent 确认**

```
spawn_subagent(worker) → file_write 需确认
  → UI 暂停 + 子 Agent 树显示
  → 用户 Allow → 子任务 resume → 摘要回父 Agent
```

**CLI Agent delegation · 外接 CLI（FR-30，v0.2）**

```
用户：「用 codex 跑测试并总结」
  → spawn_cli_agent(provider=codex, goal=…)
  → 确认 UI → subprocess(codex exec …)
  → stdout 摘要回 LLM → 灵犀回复
```

---

## 6. Non-Goals (v0.2) · 非目标

- Multi-user / cloud backend
- Native mobile apps
- MCP HTTP/SSE (deferred FR-15)
- Sub-agent cron / scheduled batch beyond inline spawn
- IM gateway as primary UI (FR-16 backlog)
- Fully autonomous shell/file without confirmation
- LangGraph migration
- Mascot / 桌宠窗口（已移除，知识库用 workspace 页）

---

## 7. System Architecture · 系统架构

```
┌──────────── Electron Desktop ────────────┐
│  chat · settings · workspace (Shibei KB) │
│  markdown-it + DOMPurify                 │
│  SSE: /api/chat/progress/{trace_id}      │
└──────────────────┬───────────────────────┘
                   │ localhost:8765
┌──────────────────▼───────────────────────┐
│  ChatService → PromptGate → sync_routing │
│           → TurnOrchestrator             │
│           → AgentLoop (+ spawn_subagent) │
│           → SubAgentRunner (pause/resume)│
│           → spawn_cli_agent (FR-30)      │
│  Scheduler: sync · briefing · think      │
└──────────┬─────────────┬─────────────────┘
           │             │
    ~/.lumina/      Shibei app
    SQLite sync     config.yaml + ~/.shibei/db  ← 读记忆主路径
    Lumina MD
```

**知识读取优先级**

1. `shibei_search` — Shibei 语义索引（个人笔记、简历、文章）
2. `session_search` — 历史对话
3. `search_memory` — Lumina 连接器同步库（备选）
4. Lumina `MEMORY.md` / `USER.md` — 稳定事实与用户偏好

---

## 8. Functional Requirements · 功能需求

| ID | Requirement · 需求 | Priority | Status |
|----|---------------------|----------|--------|
| FR-01 | Streamed chat | P0 | Done |
| FR-02 | Confirm shell/write/delete | P0 | Done |
| FR-03 | Read/list without confirm | P0 | Done |
| FR-04 | SSE tool progress | P0 | Done |
| FR-05 | Pause & timeout UI | P0 | Done |
| FR-06 | Connector sync (optional) | P0 | Done |
| FR-07 | Edit memory/profile | P0 | Done |
| FR-08 | Skills UI | P0 | Done |
| FR-09 | MCP stdio | P0 | Done |
| FR-10 | Bilingual UI | P1 | Done |
| FR-11 | Think + daily summary | P1 | Done |
| FR-12 | Thread persistence | P1 | Done |
| FR-13 | Hermes import | P1 | Done |
| FR-14 | Sub-agents Phase 2 | P2 | Done |
| FR-17 | Logo & macOS branding | P1 | Done |
| FR-18 | Grounding v2 | P1 | Done |
| FR-19 | Web search / weather | P1 | Done |
| FR-20 | Trust / anti-hallucination | P1 | Done |
| FR-21 | GitHub Actions CI | P1 | Done |
| **FR-22** | **Shibei KB integration** | P0 | **Done** |
| **FR-23** | **Shibei-first memory read routing** | P0 | **Done** |
| **FR-24** | **Sub-agent pause/resume + tree UI** | P1 | **Done** |
| **FR-25** | **KB workspace UI (replace mascot)** | P1 | **Done** |
| **FR-26** | **Chat Markdown (markdown-it + DOMPurify)** | P1 | **Done** |
| FR-15 | MCP HTTP/SSE | P2 | Planned |
| FR-16 | IM gateways | P3 | Backlog |
| **FR-27** | **Bundled Python for .dmg** | P2 | Planned |
| **FR-28** | **Explore cheap-model routing** | P2 | Planned |
| **FR-29** | **Web search API (Brave/Tavily)** | P2 | Planned |
| **FR-30** | **CLI Agent delegation (`spawn_cli_agent`)** | **P1** | **Core Done; provider integration ongoing** |

---

## 4.8 CLI Agent Delegation · 外接 CLI Agent（FR-30）

### 目标

在不嵌入外部 runtime（Hermes `AIAgent`、OpenCode worker、Claude Code TS loop）的前提下，通过 **`spawn_cli_agent` 工具** 把重任务委派给本机已安装的 CLI Agent（Codex、Claude Code、OpenCode、Cursor Agent CLI 等），并复用灵犀现有的 **确认流、SSE 进度、摘要回传** 协议。

### 与现有能力的关系

| 能力 | 关系 |
|------|------|
| `spawn_subagent` | 内层自研 loop；适合轻量 explore/worker |
| `spawn_cli_agent` | 外层 CLI 进程；适合重代码任务、专用 CLI 能力 |
| `shell` | 通用命令；无 session、无摘要协议、确认粗糙 |
| MCP stdio | 原子工具；非整 Agent 委派 |

**原则：** 父 Agent 只见 CLI 的 **最终摘要 + 退出码**；CLI 中间 stdout 不进主 context（对齐 Codex Thread / Claude Agent tool）。

### 工具接口（草案）

```json
{
  "name": "spawn_cli_agent",
  "arguments": {
    "provider": "codex",
    "goal": "在 ~/Documents/My Projects/Lumina 跑 pytest 并总结失败用例",
    "context": "分支 feat/logo-subagent-grounding；只读除测试修复外不改业务代码",
    "cwd": "~/Documents/My Projects/Lumina",
    "timeout": 600
  }
}
```

| 参数 | 说明 |
|------|------|
| `provider` | `~/.lumina/cli-agents.json` 中的预设名 |
| `goal` | 委派给 CLI 的自包含任务描述 |
| `context` | 可选约束、路径、事实 |
| `cwd` | 工作目录（默认 `shell_working_dir`） |
| `timeout` | 秒；上限由 provider 配置 cap |

### 配置文件 · `~/.lumina/cli-agents.json`

```json
{
  "providers": {
    "codex": {
      "command": "codex",
      "args": ["exec", "--full-auto"],
      "prompt_mode": "argv_tail",
      "timeout": 600,
      "needs_confirmation": true,
      "summary": {
        "from": "stdout",
        "max_chars": 8000
      }
    },
    "claude": {
      "command": "claude",
      "args": ["-p", "--output-format", "text"],
      "prompt_mode": "argv_tail",
      "timeout": 300,
      "needs_confirmation": true
    },
    "opencode": {
      "command": "opencode",
      "args": ["run"],
      "prompt_mode": "stdin",
      "timeout": 600,
      "needs_confirmation": true
    }
  },
  "defaults": {
    "provider": "codex",
    "needs_confirmation": true
  }
}
```

| 字段 | 说明 |
|------|------|
| `prompt_mode` | `argv_tail`（goal 拼到 argv 末尾）或 `stdin`（goal+context 写入 stdin） |
| `needs_confirmation` | 默认 true；委派前走现有确认 UI |
| `env` | 可选额外环境变量（不含 secrets；secrets 走 env） |
| `available_check` | 可选 `which` 命令名；未安装时工具返回明确错误 |

### 运行时行为

```
用户：「用 codex 修一下 failing tests」
  → PromptGate → full_agent / orchestrator
  → LLM 调用 spawn_cli_agent(provider=codex, goal=…)
  → [确认] 允许委派给 codex？（显示 cwd + goal 摘要）
  → subprocess：隔离 cwd，捕获 stdout/stderr
  → SSE：cli_agent_started / cli_agent_finished
  → 截断 stdout → 摘要字符串 → 作为 tool result 回 LLM
  → 灵犀整合后回复用户
```

### 权限与模式

| Agent profile | `spawn_cli_agent` |
|---------------|-------------------|
| **build** | 可用（确认后） |
| **plan** | 禁用 |
| **orchestrator** | **推荐** — 只编排，重活外委派 |

与 `spawn_subagent` 相同：**depth=1**，CLI Agent 不能再调 `spawn_cli_agent`（配置层禁用）。

### 安全

- 默认 **需用户确认**；可会话级「允许本次 CLI 委派」
- 不自动注入 API key；继承用户 shell env
- `cwd` 必须存在且在用户 home 或 `projects_dir` 下（路径校验）
- 超时 kill 进程组；记录 audit log 到 `~/.lumina/logs/cli-agent/`

### 实现路径（分阶段）

| Phase | 交付 | Acceptance |
|-------|------|------------|
| **30a** | `CliAgentConfigStore` + `spawn_cli_agent` 工具 + subprocess 摘要 | 单测 + mock CLI |
| **30b** | 设置 UI：providers 列表、测试连接、启用/禁用 | Playwright smoke |
| **30c** | SSE 进度 + 确认 UI 文案 | 桌面端可见「正在运行 codex…」 |
| **30d** | Provider 适配：`codex`、`claude -p` | 各 1 条集成测试（可选 mark manual） |
| **30e** | Orchestrator 系统提示优先委派 CLI | 文档 + prompt 片段 |

### 非目标（FR-30 v1）

- 解析 CLI 流式 JSON-RPC（Codex App Server 全协议）
- CLI 子 session 断点续跑 / resume（v2）
- 并行多个 CLI Agent（v2；先串行）
- 替代 `spawn_subagent` 内层 loop

---

## 9. UX & Content · 体验与文案

- Bilingual: **English · 中文**
- User: **Me · 我** · Bot: **Lumina · 灵犀**
- Empty KB: 引导 **Shibei 知识库** 优先，「同步」标注为备选
- Grounding: **Verified · 已核实** / **Unverified · 未核实**
- Chat 默认 Markdown 预览（markdown-it 渲染，DOMPurify 清洗）

---

## 10. Security & Privacy · 安全与隐私

- Data under `~/.lumina/` and user-configured Shibei paths; no telemetry in v0.1.x
- Secrets via env / config — never in git
- Shell runs with user OS permissions in `shell_working_dir`
- MCP servers are user-trusted child processes
- Background review must not persist assistant-invented facts
- Chat HTML: `html: false` in markdown-it + DOMPurify sanitize

---

## 11. Success Metrics · 成功指标

| Metric · 指标 | Target | Current |
|---------------|--------|---------|
| Test suite | Green on CI | **301** tests |
| Shibei read without sync | User can query KB with zero connector sync | **Done** (manual QA) |
| Memory write | Not blocked by sync_empty | **Done** |
| Filesystem grounding | No fake listings when tools ran | Automated + manual |
| Cold start (excl. LLM) | <30s | Manual QA |

---

## 12. Roadmap · 路线图

### Shipped · v0.1.1 (tag `v0.1.1`)

- E2E smoke (API + Playwright)
- Shibei agent tools + settings
- Sync empty guard; grounding hardening
- Web agent / browser routing

### Shipped · feat/logo-subagent-grounding (待合入 main → **v0.1.2**)

- Sub-agent **pause/resume** + progress **tree UI**
- Agent profiles: build / plan / orchestrator
- **Shibei KB workspace**（移除 mascot）
- 直连 Shibei native config（非 shadow `~/.lumina/shibei/`）
- Profile 保存修复（user 层 / chat facts 分离）
- Read-only tools skip confirm
- **Shibei-first** sync_routing + LIGHT tool defaults
- **Memory write** 路由修复
- **markdown-it + DOMPurify** 聊天 Markdown

---

### Next · v0.2 (按优先级)

#### Sprint A — 合入与稳定（1–2 天）

| # | Task | Owner | Acceptance |
|---|------|-------|------------|
| A1 | Merge `feat/logo-subagent-grounding` → `main`，tag **v0.1.2** | Dev | CI green |
| A2 | Commit 未合入改动（markdown vendor、routing tests） | Dev | 无遗漏 untracked vendor |
| A3 | Manual smoke：读记忆 / 写记忆 / 子 Agent 确认树 / KB 页 | QA | 截图 checklist |
| A4 | 更新 `harness-design.md` sync 文案与 Phase 3 状态 | Dev | 与 PRD 一致 |

#### Sprint B — 知识与会话（P1，~1 周）

| # | Task | Detail | FR |
|---|------|--------|-----|
| B1 | Shibei 空结果 UX | Agent 自动 `shibei_import` 或 UI 一键导入提示 | FR-22 |
| B2 | 连接器问答降级链 | weread/feishu 问句：shibei → search_memory → 明确「无数据」 | FR-23 |
| B3 | Briefing / Think 数据源 | 优先 Shibei + Lumina；连接器 sync 仅作补充 | FR-06 |
| B4 | Chat 会话持久化 v2 | 多会话列表 / 切换（desktop `localStorage` + API） | FR-12 |
| B5 | Markdown 增强 | GFM 表格（可选 plugin）；代码块 copy 按钮 | FR-26 |
| B6 | Legacy workspace 收束 | `/api/kb/*` 标记 legacy；sync 不再默认 export workspace | FR-22 |

#### Sprint C — 平台、外接 CLI 与成本（P1–P2，~2–3 周）

| # | Task | Detail | FR |
|---|------|--------|-----|
| **C0a** | **`spawn_cli_agent` 核心** | Config store、`CliAgentRunner`、subprocess 摘要、路径校验 | **Done** |
| **C0b** | **确认 + SSE** | `cli_agent_started/finished`；build/orchestrator 权限过滤 | Done |
| **C0c** | **设置 UI** | CLI Agents 面板：provider 列表、测试、启用开关 | Done |
| **C0d** | **Provider 适配** | `codex exec`、`claude -p` 首批 | FR-30 |
| C1 | Explore 便宜模型 | `explore` 子 Agent 路由到小模型 / 低 max_tokens | FR-28 |
| C2 | Web search API | Brave 或 Tavily 替代 HTML scrape | FR-29 |
| C3 | MCP HTTP/SSE | 远程 MCP server 传输 | FR-15 |
| C4 | Packaged Python | electron-builder embed venv 或 sidecar | FR-27 |
| C5 | E2E 扩展 | pause 按钮、Shibei 读记忆、子 Agent resume | FR-21 |

#### Sprint D — 触达（P3， backlog）

- FR-16 IM gateways（飞书 bot 等）
- 自定义 primary agent 注册（`~/.lumina/subagents/*.md` `mode: primary`）

---

## 13. Implementation Index · 实现索引

| Area | Path |
|------|------|
| Agent loop | `src/secretary/agent/loop.py` |
| Chat orchestration | `src/secretary/agent/chat_service.py` |
| Grounding | `src/secretary/agent/grounding.py` |
| Sync / Shibei routing | `src/secretary/agent/sync_routing.py` |
| Shibei service | `src/secretary/services/shibei_service.py` |
| Sub-agents | `src/secretary/agent/subagent/` |
| Sub-agent pause/resume | `subagent/resume.py`, `spawn_tool.py` |
| **CLI Agent** | `cli_agent/` · `spawn_cli_agent` · `~/.lumina/cli-agents.json` |
| Prompt gate | `src/secretary/agent/prompt_gate.py` |
| Chat UI + Markdown | `desktop/ui/chat.js`, `markdown.js`, `vendor/` |
| KB workspace UI | `desktop/ui/workspace.html`, `workspace.js` |
| Harness design | [harness-design.md](harness-design.md) |
| Harness comparison | [4-harness-comparison.md](4-harness-comparison.md) |
| README | [README.md](../README.md) |

---

## 14. Open Decisions · 待决事项

| Topic | Options | Recommendation |
|-------|---------|----------------|
| Memory read default | Shibei only vs Shibei + search_memory parallel | **Shibei first**; search_memory on miss or connector Q |
| Sync positioning | Required vs optional | **Optional**; document in onboarding |
| Shibei vs Lumina shadow config | Duplicate config vs native | **Native only** (current) |
| Packaged Python | embed venv vs require pip | v0.2 spike C4 |
| Web search | Scrape vs API | v0.2 API (Brave/Tavily) |
| CLI vs internal subagent | 全走 CLI vs 分层 | **重任务 CLI**（codex/claude）；**轻 explore** 走 `spawn_subagent` |
| CLI confirmation | 每次确认 vs 会话授权 | 默认每次；可选 session grant（同 shell） |
| CLI stdout | 全量 vs 摘要 | **摘要进 LLM**；全量落盘 `~/.lumina/logs/cli-agent/` |

---

*End of document · 文档结束*
