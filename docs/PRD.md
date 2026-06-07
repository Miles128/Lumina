# Lumina · 灵犀 — Product Requirements Document

**Version:** 0.1.0  
**Author:** 四海 (myx28@qq.com)  
**Last updated:** 2026-06-04  
**Status:** Active development (v0.1 feature-complete; release hardening)

<p align="center">
  <img src="assets/logo.png" alt="Lumina logo" width="96" />
</p>

---

## 1. Product Vision · 产品愿景

### English

Lumina is a **local-first personal AI secretary** for a single user. It runs on the user's machine, connects to OpenAI-compatible LLMs, and acts as a persistent assistant that knows the user's context through synced data sources, durable memory, and tool use — without turning into a generic chatbot.

Design principles:

- **Local & private** — data stays on device by default (`~/.lumina/`)
- **Action-oriented** — reads files, runs commands, searches memory, fetches the web; risky actions require explicit confirmation
- **Transparent** — tool progress and streaming replies are visible; no fake “thinking” filler
- **Grounded** — filesystem and personal-memory answers must be backed by tool output (native `list_dir` / `file_read` / `search_files`, `search_memory`, or MCP read tools); anti-hallucination guards with verified exceptions
- **Minimal UI** — dense Electron desktop chat; bilingual labels (English · 中文)
- **Hermes-compatible** — reuses LLM config, SOUL, MCP servers, and memory patterns where useful
- **Harness-first sub-agents** — delegation via `spawn_subagent` (Cursor / Hermes / Codex pattern), not LangGraph

### 中文

灵犀（Lumina）是一款**本地优先的个人 AI 秘书**，面向单一用户。应用在用户本机运行，接入 OpenAI 兼容大模型，通过数据源同步、持久记忆和工具调用持续理解用户上下文。

设计原则：

- **本地与隐私** — 数据默认留在本机（`~/.lumina/`）
- **能干活** — 可读文件、执行命令、搜记忆、联网；高风险操作必须确认
- **过程可见** — 工具进度与流式回复对用户可见
- **有依据** — 文件与记忆类回答必须基于工具结果；MCP 读盘结果与内置工具同等计入 grounding
- **界面克制** — 紧凑桌面聊天；双语标签（先英后中）
- **兼容 Hermes** — 复用 LLM、SOUL、MCP、记忆模式
- **Harness 式子 Agent** — 通过 `spawn_subagent` 委派，不使用 LangGraph

---

## 2. Brand · 品牌

| Asset · 资源 | Path · 路径 | Usage · 用途 |
|--------------|-------------|--------------|
| Logo | `docs/assets/logo.png`, `desktop/ui/logo.png` | README, favicon, top bar, bot avatar, About |
| macOS app icon | `desktop/icons/icon.icns` (from logo via `npm run icon`) | Packaged app shows as **灵犀** |
| Product name | **Lumina · 灵犀** | UI, docs, `electron-builder` `productName` |
| User label | **Me · 我** | Chat avatar |
| Assistant label | **Lumina · 灵犀** | Chat / About |

**Status:** Done — logo in README, desktop UI, About panel, and macOS `.dmg` / `.app` packaging.

---

## 3. Target User · 目标用户

**Primary · 主要用户：** 产品拥有者（四海）— 用桌面应用基于个人数据提问、在可控前提下委派文件/Shell 任务、跨会话积累记忆。

**Not targeting (v0.1) · 非目标：** 团队、多租户 SaaS、移动优先、无需确认的全自动 Agent。

---

## 4. Product Scope (v0.1) · 产品范围

### 4.1 Chat & Agent · 对话与 Agent

| Capability · 能力 | Detail · 说明 | Status |
|-------------------|---------------|--------|
| Agent loop | Full 8 steps / light 3–4 steps (filesystem turns get 4) | Done |
| Tools | `list_dir`, `file_read`, `search_files`, `search_memory`, `session_search`, `web_search`, `web_fetch`, `memory`, `shell`, `file_write`, `patch`, `file_delete`, `todo`, `skills_*`, `clarify`, MCP | Done |
| **Sub-agent Phase 2** | `spawn_subagent`: **`explore`** (read-only), **`worker`** (read/write), **`verify`** (read-only review); custom `~/.lumina/subagents/*.md`; parallel **`explore` ≤2**; depth=1; summary-only return; 120s timeout | **Done** |
| Prompt gate | Rules-first (`PROMPT_GATE_ENABLED` optional LLM); sync / profile / identity / author / direct / light / full / reject | Done |
| Web & weather | `resolve_web_search` → `web_search` (`engine=auto`, retries, DDG fallback); desktop geolocation for location-aware queries | Done |
| Confirmation | Shell, file write/patch/delete; optional permanent read / session write grants | Done |
| Streaming | SSE: `reply_delta`, tool progress, `subagent_started` / `subagent_finished` | Done |
| **Grounding** | Forced read for filesystem Qs; preflight `list_dir`; MCP `[DIR]`/`[FILE]` parsing; block unverified listings & chat-history “memory”; project-author fast path; verified badge in UI | **Done** (ongoing tuning) |
| Project author gate | `open-design 作者` etc. → read `package.json` / README without LLM; not Lumina identity | Done |
| Chat routing | All turns via backend `/api/chat` (no desktop author/identity shortcut) | Done |

### 4.2 Memory & Profile · 记忆与画像

- SQLite + FTS memory store
- Hermes-style `MEMORY.md` / `USER.md`
- Background review (user-stated facts only; no assistant hallucination persistence)
- Scheduled think + daily memory summary
- Profile auto + user edit; chat-derived facts in `profile_chat_facts.md`
- **`POST /api/profile/clear-chat-derived`** — clear polluted chat facts + scheduler snapshots

**Status:** Done

### 4.3 Data Sources & Sync · 数据源与同步

- Connectors: Feishu, WeRead, Xiaohongshu, IMAP, WeChat OA, cloud drive, local documents
- Manual + scheduled sync; daily briefing
- **Note:** Reading questions require sync (e.g. WeRead); empty store must not invent book lists

**Status:** Done (connector reliability = ongoing ops)

### 4.4 Skills & Knowledge · 技能与知识库

- Skill manager UI; executable skills; knowledge workspace route

**Status:** Done

### 4.5 Settings & Desktop UI · 设置与桌面

- LLM, SOUL, memory, MCP, appearance, data sources, profile, About (with logo)
- Language: `en` | `zh` | `bi`
- Pause / timeout UX; agent progress panel; grounding verified / unverified labels
- Clear chat history; clear polluted memory

**Status:** Done

### 4.6 MCP · MCP 集成

- `~/.lumina/mcp.json`; Hermes import; **stdio** transport
- Optional filesystem server via settings quickstart
- MCP read tools (`list_directory`, `read_text_file`, …) count toward grounding

**Status:** Done (stdio). **HTTP/SSE:** Planned (FR-15)

### 4.7 Packaging & CI · 打包与持续集成

| Item | Detail | Status |
|------|--------|--------|
| **CI** | GitHub Actions: `pytest` on push/PR to `main` / `feat/**` / `fix/**`; Python **3.11 + 3.12** matrix | **Done** |
| **macOS pack** | `cd desktop && npm run pack` → `灵犀` `.dmg` with `icon.icns` | Done |
| Runtime | Packaged app still requires local Python 3.11+ and `pip install -e ".[dev]"` | Known limitation |

---

## 5. User Flows · 用户流程

**First run · 首次使用:** Install deps → configure LLM (`.env` or `~/.lumina/agent.json`) → `cd desktop && npm start` (starts backend on :8765) → optional sync → chat.

**Agent with confirmation · 需确认:** Task → propose shell/write → Allow/Deny → real output → streamed reply.

**Sub-agent · 子 Agent:** Parent calls `spawn_subagent` → child isolated loop → summary only → parent answers user.

**Filesystem / projects · 本地项目:** Ask “My Projects 里有哪些项目” → `list_dir` or MCP list → grounded listing (not “无法确认” when tools ran).

**Add MCP · 添加 MCP:** Settings → MCP → Save & Connect or Import Hermes.

---

## 6. Non-Goals (v0.1) · 非目标

- Multi-user / cloud backend
- Native mobile apps
- MCP HTTP/SSE transport (deferred to FR-15, not v0.1 launch blocker)
- Sub-agent cron / scheduled batch jobs beyond inline spawn
- IM gateway as primary UI (FR-16 backlog)
- Fully autonomous shell/file ops without confirmation
- LangGraph migration

---

## 7. System Architecture · 系统架构

```
┌──────────── Electron Desktop ────────────┐
│  logo · chat.js · settings · i18n        │
│  SSE: /api/chat/progress/{trace_id}      │
│  (all chat → POST /api/chat)             │
└──────────────────┬───────────────────────┘
                   │ localhost:8765
┌──────────────────▼───────────────────────┐
│  ChatService → PromptGate                │
│           → TurnOrchestrator             │
│           → AgentLoop (+ spawn_subagent) │
│           → SubAgentRunner               │
│    (explore | worker | verify | custom)  │
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
| FR-09 | MCP management (stdio) · MCP 管理 | P0 | Done |
| FR-10 | Bilingual UI · 双语界面 | P1 | Done |
| FR-11 | Think + daily memory summary · 后台 Think | P1 | Done |
| FR-12 | Thread persistence (desktop + backend history) · 对话持久化 | P1 | Done |
| FR-13 | Hermes import · Hermes 导入 | P1 | Done |
| FR-14 | Sub-agents Phase 2 · 子 Agent | P2 | **Done** (`explore` / `worker` / `verify`, parallel explore ≤2, custom md) |
| FR-15 | MCP HTTP/SSE transport | P2 | **Planned** |
| FR-16 | IM integration · IM 网关 | P3 | Backlog |
| FR-17 | Project logo & macOS branding · Logo 与打包品牌 | P1 | **Done** |
| FR-18 | Grounding: search_files + MCP listings · Grounding 校验 | P1 | **Done** |
| FR-19 | Unified web search / weather + geolocation · 联网与定位 | P1 | Done |
| FR-20 | Trust: memory/filesystem anti-hallucination, clear polluted memory, project author fast path · 可信度 | P1 | Done (tune in production) |
| FR-21 | GitHub Actions CI (3.11/3.12) · CI | P1 | **Done** |

---

## 9. UX & Content · 体验与文案

- Bilingual labels: **English · 中文**
- User: **Me · 我** · Bot: **Lumina · 灵犀**
- No post-reply timing filler; no hollow openers (`reply_safety`)
- Errors actionable (timeout → narrow scope; sync empty → say “先同步”)
- Grounding: **Verified · 已核实** / **Unverified · 未核实** when tools used or blocked
- Logo visible in top bar, favicon, bot avatar, About, packaged app icon

---

## 10. Security & Privacy · 安全与隐私

- Data under `~/.lumina/`; no telemetry in v0.1
- Secrets via env / config — never in git
- Shell runs with user OS permissions in configurable `shell_working_dir`
- MCP servers are user-trusted child processes
- Background review must not persist assistant-invented facts

---

## 11. Success Metrics · 成功指标

| Metric · 指标 | Target | Current |
|---------------|--------|---------|
| Test suite | Green on CI | **228** tests, Python 3.11 + 3.12 |
| Agent tasks with confirm | >90% useful output | Manual QA |
| Cold start (excl. LLM) | <30s | Manual QA |
| Memory recall (profile Q) | Relevant in top 5 after sync | Manual QA |
| Filesystem Q grounding | No fake listings when tools ran | Automated + manual |

---

## 12. Roadmap · 路线图

### Shipped (2026-06) · 已交付

- Logo, favicon, About, **macOS pack** (`灵犀`, `icon.icns`)
- **GitHub Actions CI** (pytest, 3.11/3.12)
- **Sub-agent Phase 2:** `explore` / `worker` / `verify`, parallel explore (≤2), `~/.lumina/subagents/*.md`
- Unified **web search / weather** + desktop **geolocation**
- **Grounding v2:** preflight `list_dir`, MCP list parsing, memory/personal-fact blocks, project-author fast path, UI verified labels
- **Trust:** backend-only chat routing; `clear-chat-derived` API; background review user-only facts
- Rules-first **PromptGate** (optional LLM via `PROMPT_GATE_ENABLED`)
- Resilient **web_search** (`engine=auto`, retries, DuckDuckGo Instant fallback)

### Next (v0.1.1 — release hardening) · 近期

1. **Merge** `feat/logo-subagent-grounding` → `main` and tag release
2. **E2E smoke:** My Projects listing, third-party repo author, WeRead after sync, send button, pause/timeout
3. **Connector hardening:** sync reliability, empty-state copy (“请先同步”)
4. **Docs sync:** README test count, harness docs cross-links
5. Optional: bundled Python / one-click installer for packaged app

### P1 — Capability · 能力

- Prefer native `list_dir` over MCP full-repo search for simple directory Qs (latency)
- Briefing / Think: only use synced facts
- Sub-agent: pause/resume, optional cron (explicitly out of v0.1 non-goals until designed)

### P2 — Platform · 平台

- **FR-15:** MCP HTTP/SSE transport
- Plugin-style connector SDK

### P3 — Reach · 触达

- **FR-16:** IM gateways (Feishu bot, etc.)
- Voice / mascot polish

---

## 13. Implementation Index · 实现索引

| Area | Path |
|------|------|
| Agent loop | `src/secretary/agent/loop.py` |
| Chat orchestration | `src/secretary/agent/chat_service.py` |
| Grounding | `src/secretary/agent/grounding.py` |
| Project author fast path | `src/secretary/agent/project_author.py` |
| Web routing | `src/secretary/agent/web_routing.py` |
| Sub-agents | `src/secretary/agent/subagent/` |
| Prompt gate | `src/secretary/agent/prompt_gate.py` |
| Desktop chat | `desktop/ui/chat.js` |
| CI | `.github/workflows/ci.yml` |
| Pack / icon | `desktop/package.json`, `scripts/build-app-icon.sh` |
| Harness comparison | [4-harness-comparison.md](4-harness-comparison.md) |
| Sub-agent design | [subagent-loop-comparison.md](subagent-loop-comparison.md) |
| README | [README.md](../README.md) |

---

## 14. Open Decisions · 待决事项

| Topic | Options | Recommendation |
|-------|---------|----------------|
| Default MCP for filesystem | Built-in only vs auto filesystem server | Keep both; prefer built-in `list_dir` for speed |
| Permanent read grant | Off by default vs on | Off; confirm once per session or grant in UI |
| Packaged app Python | Require manual pip vs embed venv | v0.1.1: document clearly; later embed |

---

*End of document · 文档结束*
