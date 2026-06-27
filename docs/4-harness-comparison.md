# Codex Cursor Hermes Agent, Claude Code - 4 家 Harness 横向对比

> Cursor · Codex · Hermes Agent · Claude Code · 2026-06-01

共性：**外层 Harness + 内层 while loop + 委派工具 + 隔离 context + 只回摘要**。差异在于 loop 所在层、session 模型、并行/深度限制、子 agent 类型配置。

---

## 一、主 Loop 架构对比

| 维度 | **Cursor** | **Codex** | **Hermes Agent** | **Claude Code** |
|------|------------|-----------|------------------|-----------------|
| **语言/形态** | TS，IDE Agent Runtime | **Rust** `codex-core` | Python 单文件巨型 `AIAgent` | TS CLI，`query()` 为核心 loop |
| **Loop 本质** | 主会话 model ↔ tools 循环 | `SessionTask` turn loop：采样 → tool → 写回 → 再采样 | `run_conversation()` 同步 while | `runAgent()` 建上下文 → 内部调 **`query()`** 真 loop |
| **编排表达** | Task 工具 + hooks + `/multitask` | ThreadManager + 事件队列 | tool 拦截 `delegate_task` | `AgentTool` 分流 → `runAgent` → `query` |
| **对外协议** | IDE 内 SSE / 侧边栏 | **App Server JSON-RPC**（Thread / Turn / Item） | CLI / Gateway 共用同一 loop | 终端 transcript + tool stream |
| **Context 压缩** | 内置 Explore 等子 agent 扛噪声 | turn 内 **compaction** | 自研压缩 + session DB | 长上下文 + 子 agent 分流 |
| **并行 tool** | 支持（多 Task 同消息） | ToolRouter | `ThreadPoolExecutor` | 多 Agent call 可并行 |

**Loop 分层（抽象一致）：**

```
Harness（权限 / 会话 / UI 事件 / 确认）
    └── Agent Loop（while: LLM → tool → history → LLM）
            └── Spawn 工具（子 loop 再跑一遍，但更窄）
```

### 参考链接

- [Cursor Subagents 文档](https://cursor.com/docs/subagents)
- [OpenAI：Unrolling the Codex agent loop](https://openai.com/index/unrolling-the-codex-agent-loop/)
- [Hermes：Subagent Delegation](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation)
- [Claude Code：Subagents in the SDK](https://code.claude.com/docs/en/agent-sdk/subagents)

---

## 二、Sub-agent 怎么「生」

| 维度 | **Cursor** | **Codex** | **Hermes** | **Claude Code** |
|------|------------|-----------|------------|-----------------|
| **入口** | **`Task` 工具** | **`AgentControl.spawn`** | **`delegate_task` 工具** | **`Agent` 工具** |
| **触发** | 主 agent 自动或用户 `/multitask` | 主 session 委派 | 主 agent 调 tool（`run_agent` 内拦截） | 主 session 调 Agent tool |
| **子实例** | 新 context window + 可选 model | 新 **Thread** / core session | 新 **`AIAgent` 实例** | `runAgent()` 新 runtime |
| **配置来源** | `.cursor/agents/*.md` | agent 配置 / 类型 | `role` + `toolsets` + `config.yaml` | `.claude/agents/*.md` + built-in 类型 |
| **内置类型** | Explore 等（省 context 的重活） | 按 spawn 参数 | `leaf` / `orchestrator` | Explore、Plan、Verify、general-purpose |

---

## 三、Context 隔离与回传

| 维度 | **Cursor** | **Codex** | **Hermes** | **Claude Code** |
|------|------------|-----------|------------|-----------------|
| **子能否看父聊天** | **不能**（仅 dispatch prompt） | **不能**（新 thread） | **不能**（空对话 + goal/context） | **不能**（仅 Agent prompt 字符串） |
| **父能否看子中间步** | **不能**（只见 summary） | 只见 Item 聚合结果 | 只见 final summary | 只见 final output |
| **特殊路径** | — | thread fork | — | **fork** 可继承父 context（缓存优化） |
| **信息通道** | Task 的 prompt 参数 | spawn 时传入 context | `goal` + `context` 字段 | Agent tool 的 prompt |

**四家共识：** 中间 tool 轨迹不进父 context，否则主窗口很快爆 token。

---

## 四、工具权限（Least Privilege）

| 维度 | **Cursor** | **Codex** | **Hermes** | **Claude Code** |
|------|------------|-----------|------------|-----------------|
| **按类型收窄** | 每个 subagent md 定义能力 | spawn 时定 tool 集 | `toolsets` + role 剥离工具 | archetype：Explore 只读、Verify 审查等 |
| **子能否再 spawn** | 可嵌套但受限（2.5+） | depth limit | 默认 **leaf 无 delegate**；orchestrator 可开 | **子工具集不含 Agent**（硬禁） |
| **子禁用的能力** | 按 agent 定义 | 按 agent 配置 | leaf 禁：delegate、clarify、memory… | 按 frontmatter `tools` 白名单 |
| **危险操作** | 继承 IDE 权限模型 | **pause turn → client approve** | 子有独立 terminal；父 interrupt 取消子 | permission mode + hooks |

---

## 五、深度、并行、配额

| 维度 | **Cursor** | **Codex** | **Hermes** | **Claude Code** |
|------|------------|-----------|------------|-----------------|
| **默认深度** | 1 层为主，可树状 | depth-limited | **`max_spawn_depth=1`（flat）** | **严格 1 层**（子不能再 spawn） |
| **嵌套** | 子可 launch 子（policy/hooks 可挡） | 主→子，有上限 | 可选 depth 2–3 + `role=orchestrator` | 编排只在**主 session**；大规模用 **Workflow** 脚本 |
| **并行** | **`/multitask`**、多 Task 同发 | 多 thread | **batch ≤3**，ThreadPool | 主 session 并行调多个 Agent |
| **文件隔离** | **git worktree**（并行改文件） | 沙箱 / 工作区 | 独立 terminal session | worktree 可选 |
| **成本控** | 子 agent 可用更快/便宜 model | spawn 上限 | 3×3×3=27 并发上限警告 | fan-out 在主 session，子不递归 |

---

## 六、持久化与会话模型

| 维度 | **Cursor** | **Codex** | **Hermes** | **Claude Code** |
|------|------------|-----------|------------|-----------------|
| **会话单元** | Agent 会话 + 子 sidebar | **Thread → Turn → Item** | SQLite session + MEMORY.md | transcript + session |
| **断点续跑** | background Task + agent ID | thread resume + rollout | session 持久 | 长任务 skill + state 文件（社区模式） |
| **子 session 标识** | 子 agent 条目 / ID | 独立 thread + nickname | child AIAgent + depth 计数 | `parent_tool_use_id` 关联 |

- **Codex** 的 Thread / Turn / Item 模型协议化程度最高。
- **Hermes** 以 SQLite session + MEMORY.md 为持久化单元。
- **Cursor / Claude Code** 采用「Task 工具 + markdown 定义 agent」模式。

---

## 七、Human-in-the-loop

| 维度 | **Cursor** | **Codex** | **Hermes** | **Claude Code** |
|------|------------|-----------|------------|-----------------|
| **确认模型** | hooks + IDE 确认 | **server 暂停 turn**，等 client JSON-RPC | 父 interrupt → 子全停 | permission + hooks |
| **子内确认** | 可配 | 双向 App Server | 子独立 terminal | subagent permission mode |
| **桌面类应用适配** | 中（偏 IDE） | 高（pause/resume 成熟） | 中 | 高 |

---

## 八、总览评分表

| 能力 | Cursor | Codex | Hermes | Claude Code |
|------|:------:|:-----:|:------:|:-----------:|
| 自研 loop | ✓ | ✓ | ✓ | ✓ |
| Spawn = 工具 | Task | AgentControl | delegate_task | Agent |
| 子 context 隔离 | ✓ | ✓ | ✓ | ✓ |
| 只回摘要 | ✓ | ✓ | ✓ | ✓ |
| 子默认不能再 spawn | 软限 | 硬限 | 硬限（可配 orchestrator） | **硬限** |
| 并行 sub-agent | **强** | 中 | **batch 3** | 强（主 session 编排） |
| 类型化 sub-agent | md 文件 | 配置 | role + toolsets | md + built-in |
| 文件并行隔离 | **worktree** | 工作区 | terminal | worktree 可选 |

---

## 九、各家「杀手锏」一句话

| 产品 | Loop | Sub-agent |
|------|------|-----------|
| **Cursor** | IDE 当 **Agent 执行运行时** | **Task + worktree + `/multitask`**，并行改 repo 最强 |
| **Codex** | Rust **Session turn loop** + App Server | **Thread 树 + AgentControl + 双向 approve**，协议最完整 |
| **Hermes** | 一个 **Python while** 打天下 | **`delegate_task` 最直白**，batch 并行 |
| **Claude Code** | **`query()` 统一 loop**，spawn 只是多调一层 | **Agent 类型化 + 硬禁递归**，Explore/Verify 产品化最好 |
