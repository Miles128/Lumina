# Lumina · 灵犀 — Product Requirements Document

**Version:** 0.1.0  
**Author:** 四海 (myx28@qq.com)  
**Last updated:** 2026-06-02  
**Status:** Active development

<p align="center">
  <img src="assets/logo.png" alt="Lumina logo" width="96" />
</p>

---

## 1. Product Vision · 产品愿景

### English

Lumina is a **local-first personal AI secretary** for a single user. It runs on the user's machine, connects to OpenAI-compatible LLMs, and acts as a persistent assistant that knows the user's context through synced data sources, durable memory, and tool use — without turning into a generic chatbot.

Design principles:

- **Local & private** — data stays on device by default (`~/.lumina/`)
- **Action-oriented** — the agent reads files, runs commands, searches memory, and fetches the web; risky actions require explicit confirmation
- **Transparent** — tool progress and streaming replies are visible; no fake “thinking” filler
- **Grounded** — filesystem answers must come from tool output (`list_dir`, `file_read`, `search_files`); anti-hallucination guards with sensible exceptions for verified search results
- **Minimal UI** — dense desktop chat; bilingual labels (English · 中文)
- **Hermes-compatible** — reuses LLM config, SOUL, MCP servers, and memory patterns where useful
- **Harness-first sub-agents** — delegation via `spawn_subagent` tool (Cursor/Hermes/Codex pattern), not LangGraph

### 中文

灵犀（Lumina）是一款**本地优先的个人 AI 秘书**，面向单一用户。应用在用户本机运行，接入 OpenAI 兼容大模型，通过数据源同步、持久记忆和工具调用持续理解用户上下文。

设计原则：

- **本地与隐私** — 数据默认留在本机（`~/.lumina/`）
- **能干活** — 可读文件、执行命令、搜记忆、联网；高风险操作必须确认
- **过程可见** — 工具进度与流式回复对用户可见
- **有依据** — 文件类回答必须基于工具结果；`search_files` 命中经校验后可正常列出文件名
- **界面克制** — 紧凑桌面聊天；双语标签（先英后中）
- **兼容 Hermes** — 复用 LLM、SOUL、MCP、记忆模式
- **Harness 式子 Agent** — 通过 `spawn_subagent` 委派（对齐 Cursor / Hermes / Codex），不使用 LangGraph

---

## 2. Brand · 品牌

### English

| Asset | Path | Usage |
|-------|------|--------|
| Logo | `docs/assets/logo.png`, `desktop/ui/logo.png` | README, favicon, top bar, bot avatar, About panel |
| Product name | **Lumina · 灵犀** | UI, docs |
| User label | **Me · 我** | Chat avatar |
| Assistant label | **Lumina · 灵犀** | Chat / About |

### 中文

| 资源 | 路径 | 用途 |
|------|------|------|
| Logo | `docs/assets/logo.png`、`desktop/ui/logo.png` | README、favicon、顶栏、助手头像、关于面板 |
| 产品名 | **Lumina · 灵犀** | 界面与文档 |
| 用户 | **Me · 我** | 聊天头像 |
| 助手 | **Lumina · 灵犀** | 聊天 / 关于 |

---

## 3. Target User · 目标用户

### English

**Primary:** The owner (四海) — wants one desktop app to ask about personal data, delegate file/shell tasks with guardrails, and accumulate memory across sessions.

**Not targeting (v0.1):** teams, multi-tenant SaaS, mobile-first, or fully autonomous agents without confirmation.

### 中文

**主要用户：** 产品拥有者 — 用桌面应用基于个人数据提问、在可控前提下委派文件/Shell 任务、跨会话积累记忆。

**非目标（v0.1）：** 团队、多租户、移动优先、无需确认的全自动 Agent。

---

## 4. Product Scope (v0.1) · 产品范围

### English

#### 4.1 Chat & Agent

- Multi-turn agent loop (8 steps full / 3 light)
- Tools: filesystem, shell, search, memory, web, todo, skills, clarify, MCP
- **Sub-agent Phase 1:** `spawn_subagent` with `explore` archetype (read-only); depth=1; summary-only return
- Prompt gate: sync / profile / direct / light / full / reject
- Confirmation for shell and file mutations
- Streaming via SSE (`reply_delta`, tool progress, `subagent_started` / `subagent_finished`)
- **Grounding:** forced read for filesystem questions; verify tool output against reply; allow verified multi-file listings from `search_files`

#### 4.2 Memory & Profile

- SQLite + FTS; `MEMORY.md` / `USER.md`; background review; scheduled think; daily summary; profile sync

#### 4.3 Data Sources & Sync

- Feishu, WeRead, Xiaohongshu, IMAP, WeChat OA, cloud drive, local documents; manual + auto sync; daily briefing

#### 4.4 Skills & Knowledge

- Skill manager; executable skills; knowledge workspace (legacy route)

#### 4.5 Settings & UI

- LLM, SOUL, memory, MCP, appearance, data sources, profile, About with logo
- Language: `en` | `zh` | `bi`

#### 4.6 MCP

- `~/.lumina/mcp.json`; Hermes import; stdio transport

### 中文

#### 4.1 对话与 Agent

- 多轮循环（完整 8 步 / 轻量 3 步）
- 工具：文件系统、Shell、搜索、记忆、联网、待办、技能、澄清、MCP
- **子 Agent Phase 1：** `spawn_subagent` + `explore`（只读）；深度 1；只回摘要
- Prompt 路由；Shell/写入/删除需确认
- SSE 流式与进度（含子任务事件）
- **Grounding：** 文件问题强制查证；校验回复与工具证据；`search_files` 验证通过后可列出多文件

#### 4.2–4.6

（记忆、同步、技能、设置、MCP — 同英文节）

---

## 5. User Flows · 用户流程

### English

**First run:** Install → configure LLM → start desktop → optional sync → chat.

**Agent with confirmation:** Task → propose shell/write → user Allow/Deny → real output → streamed reply.

**Sub-agent explore:** Parent delegates research → child runs isolated loop → summary returned → parent synthesizes for user.

**Add MCP:** Settings → MCP → Save & Connect or Import Hermes.

### 中文

**首次使用：** 安装 → 配置 LLM → 启动 → 可选同步 → 对话。

**需确认的任务：** 任务 → 提议命令/写入 → 用户允许/拒绝 → 真实输出 → 流式回复。

**子 Agent 调研：** 主 Agent 委派 → 子 Agent 隔离执行 → 摘要回传 → 主 Agent 整合回复。

**添加 MCP：** 设置 → MCP → 保存连接或 Hermes 导入。

---

## 6. Non-Goals (v0.1) · 非目标

### English

- Multi-user / cloud backend
- Native mobile apps
- MCP HTTP/SSE transport
- Sub-agent **parallel** batch / cron jobs (Phase 2+)
- IM gateway as primary UI
- Fully autonomous shell/file ops
- LangGraph migration

### 中文

- 多用户 / 云端后端
- 原生移动 App
- MCP HTTP/SSE
- 子 Agent **并行** / Cron 任务（Phase 2+）
- IM 为主界面
- 无确认全自动操作
- 迁移至 LangGraph

---

## 7. System Architecture · 系统架构

```
┌──────────── Electron Desktop ────────────┐
│  logo · chat.js · settings · i18n        │
│  SSE: /api/chat/progress/{trace_id}      │
└──────────────────┬───────────────────────┘
                   │ localhost:8765
┌──────────────────▼───────────────────────┐
│  ChatService → PromptGate                │
│           → TurnOrchestrator             │
│           → AgentLoop (+ spawn_subagent) │
│           → SubAgentRunner (explore)     │
│  Scheduler: sync · briefing · think      │
└──────────────────┬───────────────────────┘
                   │
      ~/.lumina/ · LLM API · MCP (stdio)
```

---

## 8. Functional Requirements · 功能需求

| ID | Requirement · 需求 | Priority | Status |
|----|---------------------|----------|--------|
| FR-01 | Chat with streamed replies · 流式对话 | P0 | Done |
| FR-02 | Confirm shell/write/delete · 危险操作确认 | P0 | Done |
| FR-03 | Read/list without confirm · 只读免确认 | P0 | Done |
| FR-04 | SSE tool progress · 工具进度 | P0 | Done |
| FR-05 | Pause & timeout UI · 暂停与超时 | P0 | Done |
| FR-06 | Data source sync · 数据源同步 | P0 | Done |
| FR-07 | Edit memory/profile in Settings · 记忆/画像编辑 | P0 | Done |
| FR-08 | Skills UI · 技能管理 | P0 | Done |
| FR-09 | MCP management · MCP 管理 | P0 | Done |
| FR-10 | Bilingual UI · 双语界面 | P1 | Done |
| FR-11 | Think + daily memory summary · 后台 Think | P1 | Done |
| FR-12 | Thread persistence · 线程持久化 | P1 | Done |
| FR-13 | Hermes import · Hermes 导入 | P1 | Done |
| FR-14 | Sub-agents · 子 Agent | P2 | **Phase 1 Done** (`explore` only) |
| FR-15 | MCP HTTP transport | P2 | Planned |
| FR-16 | IM integration | P3 | Backlog |
| FR-17 | Project logo & branding · Logo 品牌 | P1 | Done |
| FR-18 | Grounding accepts verified search_files listings · Grounding 校验 search | P1 | Done |

---

## 9. UX & Content · 体验与文案

- Bilingual labels: **English · 中文**
- User: **Me · 我** · Bot: **Lumina · 灵犀**
- No post-reply timing filler; no hollow openers (`reply_safety`)
- Errors must be actionable (timeout → narrow scope)
- Logo visible in top bar, favicon, bot avatar, About

---

## 10. Security & Privacy · 安全与隐私

- Data under `~/.lumina/`; no telemetry in v0.1
- Secrets via env / config — never in git
- Shell with user permissions in `shell_working_dir`
- MCP servers are user-trusted processes

---

## 11. Success Metrics · 成功指标

| Metric · 指标 | Target |
|---------------|--------|
| Test suite | **170+** passing |
| Agent tasks with confirm | >90% useful output |
| Cold start (excl. LLM) | <30s |
| Memory recall (profile Q) | relevant in top 5 |

---

## 12. Roadmap · 路线图

### English

**Done (2026-06)**  
- Logo & branding  
- Sub-agent Phase 1 (`explore`)  
- Grounding fix for `search_files` listings  

**P1 — Capability**  
- Sub-agent `worker` / `verify` archetypes  
- Parallel explore (batch ≤2)  
- MCP HTTP transport  

**P2 — Reach**  
- IM gateways; plugin connectors; voice / mascot polish  

### 中文

**已完成（2026-06）**  
- Logo 与品牌  
- 子 Agent Phase 1（`explore`）  
- Grounding 支持经校验的 `search_files` 列表  

**P1 — 能力**  
- `worker` / `verify` 子 Agent；并行 explore；MCP HTTP  

**P2 — 触达**  
- IM 网关；连接器插件；语音 / 吉祥物  

---

## 13. References · 参考

- Repository: https://github.com/Miles128/Lumina  
- README: [README.md](../README.md)  
- Harness comparison: [4-harness-comparison.md](4-harness-comparison.md)  
- Sub-agent design: [subagent-loop-comparison.md](subagent-loop-comparison.md)  
- Agent loop: `src/secretary/agent/loop.py`  
- Sub-agent: `src/secretary/agent/subagent/`  

---

*End of document · 文档结束*
