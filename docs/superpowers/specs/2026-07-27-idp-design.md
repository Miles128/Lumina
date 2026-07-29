# Internal Delegation Protocol (IDP) · 委派协议化

**日期：** 2026-07-27  
**状态：** Implemented (MVP)  
**目标：** 在不引入 swarm / A2A 的前提下，把现有浅树委派提升为**有类型的协作 harness 协议**，对齐「协作 = 协议 + 硬限拓扑」。

---

## 1. 为什么做

Lumina 已有 `spawn_subagent`、摘要回传、pause/confirm、depth=1。  
缺的是**可指着说的协议面**：信封字段、生命周期状态机、信道约束、冲突策略——以前只写在 PRD 散文里。

IDP 让面试与产品都能说清：

> 协作 harness = typed delegation protocol + hard topology limits  
> （不是 Agent 聊天室，也不是 swarm）

---

## 2. 协议面（idp/v1）

### Envelope

| 字段 | 含义 |
|------|------|
| `goal` | 自包含任务 |
| `archetype` | explore / worker / verify / plan / custom |
| `tool_scope` | 子 Agent 可见工具名集合 |
| `budget.max_rounds` | 子 loop 步数上限 |
| `budget.max_depth` | 硬限（= `MAX_SPAWN_DEPTH`，现行 1） |
| `budget.timeout_sec` | 子 run 超时 |
| `return_schema` | 固定 `summary_only` |
| `channel` | 固定 `parent_child_only` |
| `conflict_policy` | 见下 |
| `batch_id` | 并行 explore 批次（可选） |

### Lifecycle

```
spawn → running → pause_confirm | pause_ask → resume → result | fail | cancel
```

与现有 confirm / ask_user / cancel 对齐；观察层记录转换，不另起执行引擎。

### Channel

- **仅父↔子**
- `peer_channel_allowed = false`（协议常量，不仅是 PRD）
- `assert_channel_allowed()` 供未来扩展点拦截子↔子

### Conflict

| 策略 | 何时 |
|------|------|
| `parent_synthesize` | 默认；并行 explore 批次 |
| `ask_user` | 父 Agent 主动 `ask_user`（策略位预留） |
| `verify_once` | archetype=verify |

禁止：子↔子辩论、多轮互评循环。

---

## 3. 实现落点

| 组件 | 路径 |
|------|------|
| 协议类型 + Store | `src/secretary/agent/idp.py` |
| Runner 挂钩 | `src/secretary/agent/subagent/runner.py` |
| SSE `idp_update` | `progress_events.py`（`idp` 字段） |
| 只读 API | `GET /api/chat/idp/{trace_id}` |
| 观察面板 | `desktop/ui`：`#idp-panel` |

不改变：depth=1、摘要回传、不嵌入外部 Agent runtime。

---

## 4. 与非目标的边界

| 不做 | 原因 |
|------|------|
| A2A / ACP 全栈 | 进程内浅树足够；外联走 MCP/CLI |
| Swarm / 子↔子总线 | PRD 非目标；IDP 明文禁止 peer |
| 通用 `spawn_cli_agent` | 已 Removed；不借 IDP 恢复 |

树状更深拓扑见 `2026-07-27-tree-swarm-agent-design.md`（**仅设计**）。

---

## 5. 面试话术（一句话）

「我们把委派做成 IDP：信封约束权限与预算，生命周期对齐 HITL，信道只允许父↔子，冲突用 parent_synthesize / ask_user / verify_once——协作带宽来自协议，不是来自 Agent 互相吵架。」
