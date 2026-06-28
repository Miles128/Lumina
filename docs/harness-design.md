# Lumina Harness Design · 自研 Runtime 设计原则

> 参考 Claude Code、OpenCode、Hermes Agent 的**设计思路**，不嵌入它们的 runtime。  
> 抽象对比见 [4-harness-comparison.md](4-harness-comparison.md)、[subagent-loop-comparison.md](subagent-loop-comparison.md)。

---

## 1. 分层（四家共识）

```
Harness（灵犀专有）
  ├── 路由 PromptGate · grounding · sync · Electron SSE · 确认流
  └── AgentLoop（while: LLM → tool → history）
        └── spawn_subagent（子 loop，隔离 context，只回摘要）
```

**不复用 runtime** = 不 import Hermes `AIAgent`、不嵌 OpenCode TS worker；只复用**协议与权限模型**。

---

## 2. 三家思路在灵犀的映射

| 来源 | 核心思路 | Lumina 实现 |
|------|----------|-------------|
| **OpenCode** | Permission ruleset：模型看不到的工具就不会被调用 | `agent_profile.py` → `resolve_parent_tools()` |
| **OpenCode** | Primary agents：`build` / `plan` / orchestrator | 设置 → Agent 模式：`build` · `plan` · `orchestrator` |
| **OpenCode** | 子 session 委派 + 并行 Task | `spawn_subagent` + `goals[]` 最多 3 路 explore |
| **Claude Code** | 类型化 subagent + md 定义 + **子 agent 禁递归** | `explore` / `worker` / `verify` / `plan` + `~/.lumina/subagents/*.md`；子 tool 集不含 `spawn_subagent` |
| **Hermes** | `delegate_task`、leaf 无 delegate、batch≤3 | `SpawnSubagentTool`；`MAX_SPAWN_DEPTH=1`；`MAX_PARALLEL_EXPLORE=3` |
| **Codex / Claude CLI** | 外进程 Agent、pause turn approve | **`spawn_cli_agent`（FR-30）**：subprocess + 摘要回传，不嵌 runtime |

---

## 3. Primary Agent 模式

| Profile | 工具 | 用途 |
|---------|------|------|
| **build** | 全工具 + `spawn_subagent` | 默认执行（读写、shell、委派） |
| **plan** | 只读 + clarify | 分析/规划，不改文件 |
| **orchestrator** | `spawn_subagent` + todo/skills/记忆检索 | 只编排，不直接改 repo |

配置：`~/.lumina/agent.json` → `"agent_profile": "build|plan|orchestrator"`，或设置 → 大模型 → Agent 模式。

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

以下逻辑留在 `ChatService` / `grounding` / `sync_routing`，不下沉到 loop：

- Grounding：强制读盘、Verified/Unverified
- 个人数据：**Shibei 就绪 → 不拦读记忆**；连接器 sync 空库仅作备选提示
- 身份/作者/项目 author fast path
- Shibei KB、KB workspace UI、Electron 确认 UI

---

## 6. 后续（Phase 3+）

- [x] 子任务 pause/resume（Codex turn approve 语义）
- [x] UI 子 Agent 树（OpenCode session tree）
- [x] 子 Agent 确认后父 loop 续跑（Codex turn stack，一层）
- [x] `SpawnContext.depth + 1` 硬限一层
- [x] Shibei-first 读记忆路由（sync 备选）
- [ ] Shibei 空结果 → 自动 import 或 UI 引导（v0.2 B1）
- [x] **`spawn_cli_agent` 核心**（FR-30 30a）：config store、subprocess 摘要、确认流、SSE 进度
- [ ] CLI Agents 设置 UI（FR-30 30b）
- [ ] Explore 便宜模型路由（Cursor 做法）
- [ ] `~/.lumina/subagents/*.md` 支持 `mode: primary` 注册主 Agent

---

*Lumina runtime 自研；设计对齐 Claude Code + OpenCode + Hermes，产品层保持秘书定位。*
