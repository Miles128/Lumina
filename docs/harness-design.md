# Lumina Harness Design · 自研 Runtime 设计原则

> 产品定位：本地优先的**通用 Agent 生产力工具**（非个人 AI 秘书）。  
> 参考 Claude Code、OpenCode、Hermes Agent 的**设计思路**，不嵌入它们的 runtime。  
> 抽象对比见 [4-harness-comparison.md](4-harness-comparison.md)、[subagent-loop-comparison.md](subagent-loop-comparison.md)。  
> 产品需求与集成原则见 [PRD.md](PRD.md)。

---

## 1. 分层（四家共识）

```
Harness（灵犀专有）
  ├── 路由 PromptGate · grounding · Electron SSE · 确认流
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
- [x] **Skill 编排 / 工作流 DAG（F26）** — **画布 MVP 已落地**（见 [workflow-dag-design.md](workflow-dag-design.md)）；暂停/封装仍属后续
- [ ] 打包内嵌 Python（FR-27）— **Deferred**
- [ ] IM 网关（FR-16）— **Deferred**
- [ ] Git 只读工具（FR-37）— **Deferred**

---

*Lumina runtime 自研；产品层为本地通用 Agent 生产力工具。外部集成 = 标准 MCP 或 CLI。Skill 编排为规划中差异能力。*
