# DSH 插件化改造方案（Lumina → DeepSeek Harness 插件）

> **状态：已启动 · Phase 0 通过 · Slice 1–3 已落地并通过真实会话验收**
> 分支：`spike/dsh-runtime`
> 决策：**全面转 dsh runtime**；UI 寄生 dsh Desktop/Web（客户端插件），Lumina 自研 Electron 壳退役。
> 已落地：`dsh/`（`dsh-lumina` 插件，覆盖 prompt / writegate / jail / confirm / grounding / memory / trace），已安装到本机 `~/.dsh/profiles/lumina`。
> 定位：Lumina 由「独立 harness 产品」转为「DeepSeek Harness 生态的差异化插件包」，消除 PRD「不嵌入产品 runtime」冲突（见 §5.0）。

---

## 0. TL;DR

- **新定位**：harness（agent loop / LLM / 沙箱 / 委派）交给 dsh 官方 runtime；Lumina 只做**产品差异化插件**（grounding / 确认 / 对话地图 / TraceStore / Shibei / Skill）。
- **冲突消除**：原方案是「Lumina 嵌入 dsh runtime」→ 违反 PRD；插件化后关系倒转为「dsh 加载 Lumina 插件」→ 字面冲突消除，仅需修订「Harness-first 自研 harness」定位措辞。
- **范围**：Python 后端约 **30.5K 行**、测试约 **13.6K 行**重写为 dsh Cordis 插件（TS）；前端 **11.4K 行**去留取决于 §5.4。
- **决策门**：Phase 0 spike 必须回答 §5.2 的 7 个问题；任一失败则方案终止，回退 Python SDK 桥接（方案 ③）。

---

## 1. 背景

DeepSeek 官方于 2026-08 推出 **DeepSeek Harness（`dsh`）**，developer preview：

- 基于 **Cordis** 插件框架（TypeScript）：一切皆插件，`export function apply(ctx)` 注册 tools / events / services，`inject` 声明依赖；插件随 `ctx` 自动清理。
- **Cordis composition**：`cordis.yml` 声明 agent 组合（system prompt / 工具 / 模型 / 插件 / HMR）。
- 自带 **Web UI + CLI**（`dsh web`）：workspace、权限策略、委派、plan、持久化 session。
- **Python SDK**（`deepseek_harness.DeepSeekHarness`）只是启动 bundled TS runtime 的 JSONRPC 包装；真实运行时是 TS。
- 仓库：<https://github.com/deepseek-ai/deepseek-harness>；文档：<https://deepseek-harness.github.io/deepseek-harness/en/>

**动机**：dsh 是 DeepSeek 官方为 DeepSeek-V4 深度优化的 harness（reasoning / Responses API / 委派 / 沙箱），官方维护。当前 Lumina 自维护一层 openai-agents SDK 适配 + 自研 facade，本质是「自维护对 DeepSeek 的适配层」。改为插件后，harness 的维护面交给官方，Lumina 聚焦差异化。

---

## 2. 现状盘点（改造范围）

| 层 | 规模 | 说明 |
|---|---|---|
| `src/`（Python 后端） | **30,467 行** | FastAPI + harness + 服务 |
| — `src/secretary/agent/` | 20,918 行 | harness 核心（最大块，多数可弃） |
| — `src/secretary/services/` | 4,638 行 | web_search / browser / github 等 |
| — `src/secretary/api/` | 2,207 行 | FastAPI 路由（大概率拆除） |
| — `src/secretary/memory/` | 1,244 行 | SQLite 记忆 + 会话 |
| — `src/secretary/workflow/` | 1,076 行 | Skill DAG 编排 |
| — `core/utils/connectors` | ~227 行 | 少量 |
| `tests/`（Python） | **13,634 行**（714 passed） | 需迁移为 TS 测试 |
| `desktop/`（Electron） | **11,378 行**（排除 node_modules） | 去留取决于 §5.4 |

**关键结论**：agent 模块 20.9K 行里，`agents_sdk_runtime / loop / turn_runner / llm_client` 等 harness 底座**直接弃用**（dsh 原生提供）；真正需要重写的是产品差异化子集（grounding / fs_jail / write_gate / confirmation / trace_store / mcp / memory / skill / workflow / services），估约 **12–15K 行**。

---

## 3. 目标架构

```
DeepSeek Harness runtime（宿主，官方维护）
  ├── Cordis 框架（plugins / services / events / HMR）
  ├── dsh 原生服务：LLM adapter · sandbox · permission · bash · editor · 委派
  └── composition（cordis.yml）
        └── lumina-* 插件包（本项目交付物）
              ├── lumina-grounding   工具后校验 + 强制联网（自研）
              ├── lumina-confirm     确认策略（dsh permission policy 之上）
              ├── lumina-fs / lumina-writegate   文件沙箱 + WriteGate
              ├── lumina-mcp         外部 MCP 工具桥接（stdio/SSE/HTTP）
              ├── lumina-trace       TraceStore 思考链轨迹 + 导出
              ├── lumina-memory      SQLite 记忆 + 会话
              ├── lumina-skill       Skill DAG 编排
              ├── lumina-web         web_search / browser / github 服务
              └── lumina-config      可定制参数面（agent.json，FR-52）

前端（二选一，见 §5.4）
  ├── 方案 A：保留 Electron，经本地 IPC/事件对接 dsh
  └── 方案 B：放弃 Electron，用 dsh Web UI（若插件可扩展 UI）
```

---

## 4. 模块映射

| 现有 Python 模块 | 落点 |
|---|---|
| `agents_sdk_runtime.py` / `loop.py` / `turn_runner.py` / `llm_client.py` / `llm_config.py` | **弃用**（dsh LLM adapter + runtime） |
| `loop_prompting.py` / `prompt_gate.py` / `soul.py` | `lumina-prompt`（system prompt 组装） |
| `turn_models.py` / `session_store.py` / `context_snapshot.py` | dsh session + `lumina-memory` |
| `confirmation_policy.py` / `permission_guard.py` | `lumina-confirm`（permission policy 之上） |
| `grounding.py` | `lumina-grounding`（工具后钩子） |
| `fs_jail.py` / `thread_sandbox.py` | `lumina-fs`（sandbox 之上） |
| `write_gate.py` | `lumina-writegate` |
| `chat_tool_registry.py` / `tools/` / `p0_tools.py` | `ctx.tools.register(...)` |
| `mcp_manager.py` / `mcp_builtin.py` | `lumina-mcp` |
| `subagent/` | dsh 委派 + archetype 配置 |
| `trace_store.py` | `lumina-trace` |
| `context_compaction.py` | dsh compaction + `lumina-compact` |
| `progress_events.py` / `progress_hub.py` | dsh events → 前端 |
| `skills.py` / `executable_skill.py` / `workflow/` | `lumina-skill` |
| `memory/` | `lumina-memory` |
| `reply_safety*` / `reflection/` / `identity.py` / `project_author.py` / `task_intent.py` / `sync_routing.py` | 归并进对应插件 |
| `services/` | `lumina-web` |
| `api/`（FastAPI） | 拆除（Electron 直连）或方案 A 保留 |
| `harness_config.py` | `lumina-config` |

---

## 5. 关键决策与取舍

### 5.0 PRD 冲突如何消除（核心）

PRD 冲突原文（`docs/PRD.md`）：
> 「**Harness-first** … **不 fork / 不嵌入** Pi · Hermes · OpenCode · OpenWorker 产品 runtime」  
> 「非目标：LangGraph / **fork 或嵌入** Hermes·OpenCode·Pi·OpenWorker runtime」

**关系倒转是关键**：

| 表述 | 关系 | 违反 PRD？ |
|---|---|---|
| Lumina **嵌入** dsh runtime 作基座 | Lumina 拥有 harness，内部用 dsh | **违反**（嵌入产品 runtime） |
| Lumina **成为** dsh 的插件 | dsh 拥有 harness，加载 Lumina 扩展 | **不违反字面**（Lumina 不再「嵌入」别人） |

**消除的是字面冲突，不是全部纪律**。需诚实修订两条：

1. **「Harness-first / 自研 harness」** → 改为「harness 基座采用 DeepSeek Harness（官方 runtime）；Lumina 聚焦产品差异化插件」。这是定位转变，必须写进 PRD，不能靠话术绕。
2. **「不 fork / 不嵌入产品 runtime」** → 补充例外：「作为 dsh 生态插件（宿主为 dsh，非 Lumina 嵌入）不在此列」。

> 结论：插件化让 PRD 修订**小且干净**——只需改「自研 harness → 官方 harness + 自研差异化插件」的定位句，无需推翻「差异化自研」「MCP/CLI 集成」「本地优先」等其余原则。

### 5.1 「直接用 TS runtime」vs「Python SDK 桥接」

| 维度 | 插件化（本方案） | Python SDK 桥接（方案 ③） |
|---|---|---|
| harness | dsh 原生 | dsh（经 Python SDK JSONRPC） |
| Lumina 交付物 | Cordis 插件（TS） | Python 服务层保留 |
| 语言 | 全 TS（与前端统一） | 异构 |
| 差异化控制粒度 | 插件内可达（事件/钩子） | 受 JSONRPC 边界限制 |
| 投入 | 大（12–15K 行重写） | 中 |

### 5.2 高风险待验证能力（Phase 0 必须实测）

1. **MCP 支持**：dsh 是否原生支持 MCP（stdio/SSE/Streamable HTTP）作 tool 来源？Shibei / 外部工具全走 MCP，否则需自研 `lumina-mcp`。**第一否决项。**
2. **确认/HITL 语义**：dsh permission policy + 询问能否等价 pause/resume + 确认卡片（diff 预览、confirm/cancel、父→子 cancel、shell 中途取消）？
3. **工具前后钩子**：grounding / fs_jail / WriteGate 需**调用前拦截 → 校验 → 放行/阻断**的同步钩子。dsh 事件若仅异步广播则不够。**第二否决项。**
4. **会话持久化**：dsh JSONL session 能否跨重启恢复（等价 Turn 持久化 + pause bundle）？
5. **思考链轨迹**：dsh session log 能否满足 TraceStore 审计/导出（`~/.lumina/traces/*.jsonl`）？
6. **嵌入形态**：dsh runtime 能否以库嵌入 Electron 主进程（npm 依赖），还是强制独立进程 / Web UI？
7. **沙箱语义**：dsh sandbox 与 fs_jail（`code_exec` 只读工作区、禁写回、禁网、会话内免确认）是否对齐？

### 5.3 差异化保留清单（自研，不外包给 dsh）

grounding 校验 · confirmation_policy · fs_jail · WriteGate · 对话地图 · TraceStore · Shibei 集成 · Skill 编排 · `agent.json` 参数面（FR-52）· reply_safety / reflection / 身份作者 fast path / web 路由。

这些重写为 `lumina-*` 插件，不改用 dsh 内置实现。

### 5.4 前端去留（最大的战略分叉）

| 方案 | 前提 | 代价 |
|---|---|---|
| **A 保留 Electron** | dsh runtime 可库嵌入主进程 | 前端 11.4K 行保留，改对接层（SSE→events、API→IPC）；对话地图 / 确认 UI 无损 |
| **B 放弃 Electron，用 dsh Web UI** | dsh 插件**可扩展 UI**（面板/组件） | 对话地图 / 确认卡片需重写为 dsh UI 扩展；若 dsh 不支持 UI 扩展则不可行 |

> 强烈建议先走 **A**：Electron 是 Lumina 已交付的产品面（对话地图 / 确认 / 工作流画布），dsh 插件大概率只提供后端能力（tools/events/services），UI 扩展点待验证。A 失败才考虑 B。

---

## 6. 分阶段计划

### Phase 0 — Spike（唯一入口，预算 1–2 天）

临时目录装 `deepseek-harness`（git clone + npm/pnpm），**只调研，不改 Lumina 代码**：

- [ ] 最小 Cordis 插件 + `cordis.yml` 跑通一个 agent turn（bash + editor）。
- [ ] 验证 §5.2 的 7 项，输出逐条结论（通过/失败/有替代）。
- [ ] 重点确认：MCP 支持、工具前后钩子、内嵌 Electron 形态、UI 扩展点。
- [ ] 产出 **Spike 报告**：通过 → 细化 Phase 1；任一否决项失败 → 终止，回退方案 ③。

### Phase 1 — 核心差异化插件

`lumina-prompt` → `lumina-confirm` → `lumina-grounding` / `lumina-fs` / `lumina-writegate`（先验证钩子语义）→ `lumina-session`

### Phase 2 — 产品差异化层

`lumina-mcp` → `lumina-trace` → `lumina-memory` → `lumina-skill`（Skill DAG）→ `lumina-web`（服务层平移）→ archetype 委派配置

### Phase 3 — 前端对接（方案 A）

- 拆 FastAPI `api/`；Electron 主进程内嵌 dsh runtime
- SSE → dsh events；确认 UI → dsh permission 询问
- 对话地图 / 工作流画布对接新事件流

### Phase 4 — 测试迁移 + 收尾

- 714 个 Python 测试 → TS（vitest/jest），核心 harness 优先
- 端到端：Electron 冒烟、确认流、并行 explore、思考链导出
- PRD 修订归档、AGENTS.md 纪律更新

---

## 7. 风险与应对

| 风险 | 等级 | 应对 |
|---|---|---|
| dsh 为 developer preview，API 不稳定 | 高 | Phase 0 锁版本；正式版前不升级基线 |
| 工具前后钩子缺失 → grounding/fs_jail/WriteGate 失真 | 高 | Phase 1 最先验证；失败即终止 |
| MCP 不支持 → 外部工具链断裂 | 高 | Phase 0 否决项；备选自研插件（成本高） |
| 插件无 UI 扩展 → 前端必须留 Electron | 中 | 走方案 A（§5.4），影响可控 |
| 12–15K 行 Python 重写 TS 的工期与 bug 面 | 高 | 分阶段 + 测试迁移前置；每阶段独立验收 |
| 714 测试迁移丢失覆盖 | 中 | 按模块迁移，核心 harness 优先 |
| 团队 TS 熟练度 | 中 | Phase 1 由 spike 原型带教 |

---

## 8. 验收标准与决策门

**决策门（Go/No-Go）**：
1. PRD 修订通过（§5.0 定位措辞变更）。
2. Phase 0 spike：7 项能力全通过或有可接受替代。
3. 确认 dsh runtime 可库嵌入 Electron 主进程（否则评估独立进程 + IPC）。

**阶段验收**：
- Phase 1：agent turn 跑通，确认 + grounding + fs_jail + WriteGate 语义等价。
- Phase 2：Shibei / MCP / Skill / TraceStore 等价。
- Phase 3：Electron 冒烟通过，对话地图 / 确认 UI 正常。
- Phase 4：核心测试迁移完成，覆盖对齐原 714 用例关键路径。

---

## 9. Phase 0 实测结论（2026-10-25）

运行环境：dsh `0.2.1-rc.2`（npm）+ 本机 `~/.dsh/profiles/{web,desktop,weblocal}` + `dsh-forkmap` 客户端插件先例。

| # | 待验证能力 | 结论 | 证据 |
|---|---|---|---|
| 1 | MCP 支持 | ✅ 原生 | `packages/mcp`（`mcp-client` / `mcp-resources`）已随 base 挂载，工具按 server 限定命名 |
| 2 | 确认 / HITL | ✅ 等价 | `ctx.approval.request()` + `ApprovalPolicy('ask'\|'never')`；`tools/pre-execute` 返回 `ask` 即可触发，无 answerer 时 fail-closed |
| 3 | 工具前后钩子 | ✅ 同步瀑布 | `tools/pre-execute` / `tools/execute` / `tools/post-execute` / `tools/result`，可改写或阻断 |
| 4 | 会话持久化 | ✅ | JSONL session log + `session/disposed`/`flush`；恢复走 `Session.fromRestore` |
| 5 | 思考链轨迹 | ✅ | `session/event` 全量事件流（turn/step/tool/assistant），Slice 1 已落 `lumina-trace` JSONL |
| 6 | 嵌入形态 | ⚠️ 改为寄生 | dsh 无稳定嵌入式库 API；官方桌面版本身是 Electron + `dsh-web-app`，Lumina 直接做客户端插件，**不内嵌 runtime** |
| 7 | 沙箱语义 | ✅ 可叠加 | `sandbox` / `sandbox-policy` + `fs/write-intent` 事件；`lumina-jail` 在其上做工作区硬栅栏 |

**UI 扩展点**：✅ 可扩展。`package.json` 的 `dsh.client.inject` + `cordis.patch.yml` 可向 Web/Desktop UI 注入 React 组件；`dsh-forkmap`（对话地图）已在本机 web profile 运行。

**结论**：两个否决项（MCP、工具钩子）均通过；不做 runtime 内嵌，改为「dsh 宿主 + Lumina 插件 + 客户端 UI 插件」。Phase 1 直接进入垂直切片。

### Slice 1 + 2 已交付（`dsh/`）

| 模块 | 落点 | 测试 |
|---|---|---|
| `prompt` | `ctx.systemPrompt.section`（人格 + grounding 纪律） | 随插槽验证 |
| `writegate` | `subagent/start` + `tools/pre-execute`（子 Agent 只写 proposals，shell 只读） | 4 例 + 真实子 Agent 验收 |
| `jail` | `tools/pre-execute`（写盘 / shell 绝对路径越界 deny） | 4 例 + 真实会话验收 |
| `confirm` | `tools/pre-execute` → `ask`（越界写 / 任意 shell / MCP 写） | 6 例 |
| `grounding` | `session/event` 证据累积 + `agent/turn-stopping` steer 重试 | 4 例 + 真实会话验收 |
| `memory` | MEMORY.md 自动注入 + `memory` / `search_memory` 工具 | 5 例 |
| `trace` | `session/event` → `~/.lumina/traces/<session>.jsonl` | 2 例 + 真实会话验收 |

验证：`cd dsh && npm run build && npm test`（30 passed）；`dsh --profile lumina --dump-config` 可见 `id: lumina`；`dsh --profile lumina --no-open --port 3920` 正常起 Web UI。

### Slice 1 + 2 真实会话验收（2026-10-25）

在 `~/.dsh/profiles/lumina` 上用 Playwright 驱动 dsh Web UI，真实模型（DeepSeek-V4.1-Flash）：

| 场景 | 结果 |
|---|---|
| 内容问题「读一下 LUMINA_ACCEPT.md」 | ✅ 调用 `read`，4s 返回验收码 |
| 禁止用工具、凭记忆回答文件内容 | ✅ grounding 注入补读指令 → 模型改调 `glob` → `read` → 基于真实内容回答 |
| 写 `/private/tmp/lumina-escape.txt` | ✅ jail 返回 `sandbox: cannot write outside the workspace`，文件未创建，模型如实报告 |
| 子 Agent 写业务路径 `EVIL.txt` | ✅ WriteGate 连续拦截 shell 与 write；子 Agent 改写到 `.lumina/proposals/<runId>/EVIL.txt`，业务文件未创建 |
| trace | ✅ 每个会话落 JSONL，含 user / assistant / tool-call / tool-result / turn 事件 |

验收后已清理：测试文件、`.lumina/proposals/<runId>`、测试用 profile 覆盖配置全部移除。

### Slice 3 已交付：Skill + Workflow 改用 dsh 原生能力

决策：**直接用 dsh 的 workflow 脚本**，Lumina 画布式 Skill DAG 退役。

| 能力 | 配置 | 验证 |
|---|---|---|
| Skill | 启用 `skill-filesystem` + `tool-skill`；`customSkillDirs: [~/.lumina/skills]`；默认扫描 `~/.agents/skills`（47 个有效技能） | 真实会话 `skill` 工具加载 `article-flow` → 返回标题 |
| Workflow | 启用 `workflow-ptc`（provider: spawn）+ `tool-workflow` | 真实会话 `demo-ping`：1 phase / 1 agent / 3s，返回 `{ "reply": "pong" }` |

文档：`dsh/WORKFLOWS.md`（目录优先级、`SKILL.md` 格式、脚本 hook、示例、迁移状态）；profile 模板：`dsh/profile.patch.example.yml`。

旧实现处置：`src/secretary/workflow/`、`skills.py`、`executable_skill.py`、`desktop/ui/workflows.js` 停止演进，Slice 5 删除。

### 后续切片

- Slice 4：web_search / browser / MCP 策略、Shibei
- Slice 5：退役 Python `api/` 与 Electron 壳，测试迁移

---

## 10. 参考

- DeepSeek Harness 文档：<https://deepseek-harness.github.io/deepseek-harness/en/>
- GitHub：<https://github.com/deepseek-ai/deepseek-harness>
- Python SDK：<https://deepseek-harness.github.io/deepseek-harness/en/guide/python-sdk>
- Cordis 插件教程：<https://deepseek-harness.github.io/deepseek-harness/en/develop/cordis-tutorial/>
- Lumina：`docs/harness-design.md`、`docs/PRD.md`、`docs/4-harness-comparison.md`
