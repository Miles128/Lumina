# Lumina Harness Design · 自研 Runtime 设计原则

> 产品定位：本地优先的**通用 Agent 生产力工具**（非个人 AI 秘书）。  
> 参考 Claude Code、OpenCode、Hermes Agent、Pi 的**设计思路**（薄 prompt / 权限过滤等），**不 fork、不嵌入**它们的 runtime。  
> 子 Agent：**depth=1**（不可再 spawn）；多路 explore 由主 Agent 汇总；**不做**多 Agent 辩论。  
> 抽象对比见 [4-harness-comparison.md](4-harness-comparison.md)、[subagent-loop-comparison.md](subagent-loop-comparison.md)。  
> 产品需求与集成原则见 [PRD.md](PRD.md)（v0.3.1）。  
> PRD 新增一等公民：**思考链可记录/可追溯/可分析（FR-51）**、**Harness 大量可定制参数（FR-52）**。（FR-49/50 已用于工作流。）

---

## 1. 分层（四家共识）

```
Harness（灵犀专有）
  ├── 路由 PromptGate · grounding · Electron SSE · 确认流
  ├── 思考链 / 运行轨迹（可记录 · 可追溯 · 可分析）
  ├── 可定制参数面（确认 · 委派 · compaction · 轮次 · 超时 · 路由 · 轨迹保留）
  └── AgentLoop（while: LLM → tool → history）
        └── spawn_subagent（子 loop，隔离 context，只回摘要）
```

**不复用 runtime** = 不 import Hermes `AIAgent`、不嵌 OpenCode TS worker；只复用**协议与权限模型**。

**为何不用 LangGraph**：PRD 非目标。灵犀已有 `PromptGate` + `TurnRunner` + `AgentLoop`，并内建 Electron 确认流、SSE 进度、子 Agent pause/resume、可选 Shibei 路由——这些是产品专有 harness 层，LangGraph 的图状态机不会替代它们，只会增加依赖与调试面。后续若需要 cron/IM 触达，优先 **MCP + 定时任务**，而非引入通用 graph runtime。

---

## 2. 三家思路在灵犀的映射

| 来源 | 核心思路 | Lumina 实现 |
|------|----------|-------------|
| **OpenCode** | Permission ruleset：模型看不到的工具就不会被调用 | `agent_profile.py` → `resolve_parent_tools()` |
| **OpenCode** | Primary agents：`build` / `ask` / `plan` | 设置 → Agent 模式：`build` · `ask` · `plan` · `auto` |
| **OpenCode** | 子 session 委派 + 并行 Task | `spawn_subagent` + `goals[]` 最多 3 路 explore |
| **Claude Code** | 类型化 subagent + md 定义 + **子 agent 禁递归** | `explore` / `worker` / `verify` / `plan` + `~/.lumina/subagents/*.md`；子 tool 集不含 `spawn_subagent` |
| **Hermes** | `delegate_task`、leaf 无 delegate、batch≤3 | `SpawnSubagentTool`；`MAX_SPAWN_DEPTH=1`；`MAX_PARALLEL_EXPLORE=3` |
| **Codex / Claude CLI** | 外进程 Agent、pause turn approve | 子 Agent **pause/resume** + 确认流；**不**使用已删除的 `spawn_cli_agent` |

---

## 3. Primary Agent 模式

| Profile | 工具 | 用途 |
|---------|------|------|
| **build** | 全工具 + `spawn_subagent` | 默认执行（读写、shell、MCP、委派） |
| **auto** | 运行时解析为 build/ask/plan | **默认**；按问题类型自动选模式 |
| **ask** | 只读 + Shibei/记忆/联网/浏览器/MCP 只读/`ask_user` | 问答检索，不改环境 |
| **plan** | ask 子集 + todo/skills | 分析/规划，不改文件 |

配置：`~/.lumina/agent.json` → `"agent_profile": "auto|build|ask|plan"`，或聊天输入框旁模式切换。

---

## 4. Sub-agent Archetypes

| Archetype | 权限 | 对标 |
|-----------|------|------|
| `explore` | 只读 | Claude Explore / OpenCode explore |
| `worker` | 读写 + shell（确认） | OpenCode general |
| `verify` | 只读审查 | Claude Verify |
| `plan` | 只读规划 | OpenCode plan（子任务版） |
| 自定义 | `~/.lumina/subagents/*.md` frontmatter `tools:` | Claude `.claude/agents/*.md` |

---

## 5. 灵犀专有（不应放进通用 runtime）

以下逻辑留在 `ChatService` / `grounding` 等产品层，不下沉到 loop：

- Grounding：强制读盘、Verified/Unverified
- 可选知识：**Shibei 就绪 → 不拦读记忆**
- 身份/作者/项目 author fast path
- Shibei KB、KB workspace UI、Electron 确认 UI、对话地图
- **外部集成：** 标准 MCP 或 CLI（`shell` / MCP stdio）；平台专用 Connector = **Legacy frozen**（见 PRD）

---

## 6. 后续（Phase 3+）

- [x] 子任务 pause/resume（Codex turn approve 语义）
- [x] UI 子 Agent 树（OpenCode session tree）
- [x] 子 Agent 确认后父 loop 续跑（Codex turn stack，一层）
- [x] Harness P0：`TurnContext` + `SessionStore`；SSE schema v2；`TurnRunner`；`DelegationResult`
- [x] **Turn 持久化**：`SessionStore`（`~/.lumina/turns.json`）+ pause bundle 跨重启恢复
- [x] **Context compaction**：长 turn 内消息历史压缩
- [x] **Auto profile**：规则路由 ask/plan/build
- [x] `SpawnContext.depth + 1` 硬限一层
- [x] Shibei-first 读记忆路由（可选）
- [x] **Hermes runtime 解耦**：仅保留「设置 → 一键从 Hermes 导入」
- [x] Shibei 空结果 → 自动 import 或 UI 引导
- [x] ~~`spawn_cli_agent`（FR-30）~~ → **Removed**（勿恢复）
- [x] **IDP（Internal Delegation Protocol）** — 委派信封/生命周期/信道/冲突策略协议化 + 只读观察面板（`idp.py` · SSE `idp_update` · `GET /api/chat/idp/{trace_id}`）
- [ ] Explore 便宜模型路由 — **Deferred**
- [x] ~~`mode: primary` 自定义主 Agent~~ → **不做**；用 Auto profile
- [x] Web search API
- [x] MCP HTTP/SSE / Streamable HTTP（FR-15）
- [x] Harness harden：confirm/resume cancel · 父→子 cancel · shell 中途取消 · turns prune
- [x] **Eval harness（F23）**
- [x] **Compaction 可观测**
- [x] **Worker worktree 隔离**
- [x] **智能 archetype（F24）**
- [x] **结构化卡片（F25）**
- [x] **Hooks 权限层**
- [x] **Skill 编排 / 工作流 DAG（F26）** — 画布 + HumanReview/confirm_before + `mode=llm|agent`（AgentLoop 经 pause/resume；无 spawn）；见 [workflow-dag-design.md](workflow-dag-design.md)
- [ ] 打包内嵌 Python（FR-27）— **Deferred**
- [ ] IM 网关（FR-16）— **Deferred**
- [ ] Git 只读工具（FR-37）— **Deferred**
- [x] **`code_exec` 工作区只读沙箱** — 可读 `working_dir`、禁写回、禁网；Ask/Build + worker；会话内首次确认后免确认；见 [superpowers/specs/2026-07-23-code-exec-workspace-sandbox-design.md](superpowers/specs/2026-07-23-code-exec-workspace-sandbox-design.md)
- [x] **思考链轨迹（FR-51）** — `TraceStore` → `~/.lumina/traces/{trace_id}.jsonl`；SSE 扇出记录；GET/export API；聊天侧导出
- [x] **Harness 可定制参数面（FR-52）** — `HarnessConfig` 落盘 `agent.json`；max_tool_rounds / light / compaction / trace_retention / tool output；设置 → Harness 参数

---

### 思考链与可定制参数（产品约束）

| 约束 | 说明 |
|------|------|
| 企业运行友好 | 轨迹支持合规抽检、事故复盘、质量评估；非「仅开发者日志」 |
| 本地默认 | 不默认云端上报；保留策略可配置 |
| 参数面 | 默认安全合理；高级旋钮可调；硬限（如 `MAX_SPAWN_DEPTH=1`）不可被配置绕过 |
| 与可见性关系 | FR-46 解释策略 · FR-47 效率指标 · FR-51 轨迹数据 · FR-52 改策略 |

### code_exec（解题沙箱）

Agent 用 `code_exec` 写短 Python 解题：进程内 soft sandbox（非 Docker）。可读当前工作区；仅临时 cwd 可写；落盘回工作区必须 `write`/`edit`（别名 `file_write`/`patch`）。计算/解析优先 `code_exec`，勿用 `shell` 的 `python -c` 替代。

---

*Lumina runtime 自研；产品层为本地通用 Agent 生产力工具。外部集成 = 标准 MCP 或 CLI。Skill 编排为规划中差异能力。*
