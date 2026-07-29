# 树状 Swarm Agent 方案（设计稿 · 不实施）

**日期：** 2026-07-27  
**状态：** **Superseded** by [2026-07-30-controlled-tree-adversarial-mission-strip-design.md](2026-07-30-controlled-tree-adversarial-mission-strip-design.md)（PRD 0.3.2 已修订）。本文仅作历史对比。  
**关联：** [PRD.md](../../PRD.md) · [harness-design.md](../../harness-design.md) · [IDP](2026-07-27-idp-design.md)

---

## 0. 为何先写方案、不写代码

现行 Lumina 是**浅树委派 harness**（主 Agent → 子 Agent ×N ≤3 → 摘要 → 主汇总）。  
「树状 swarm」会触及 PRD 明确非目标（子再 spawn、互评、无限深度）。  
因此本方案回答三个问题：

1. 若要做，**最小可控形态**是什么？  
2. 与现行 harness / IDP / 外部联邦如何分层？  
3. **何时值得做、何时继续不做**？

---

## 1. 问题定义

### 1.1 什么叫「树状 swarm」

```
Root (orchestrator)
├── Branch A (role=explore|worker|…)
│   ├── Leaf A1
│   └── Leaf A2
├── Branch B
│   └── Leaf B1
└── Verify (optional, once)
```

与现行差异：

| 维度 | 现行（v0.3） | 树状 swarm（本方案） |
|------|-------------|---------------------|
| 深度 | 硬限 1 | 可配置 2–3（仍有硬顶） |
| 子↔子 | 禁止 | 默认仍禁止；仅经父扇入 |
| 并行 | explore ≤3 | 按层预算（见 §4） |
| 冲突 | 父合成 / ask_user / 一次 verify | 显式 ConflictPolicy |
| 产品定位 | 非协作 App | 仍非协作 App；是 **编排拓扑扩展** |

**不做（本方案范围外）：** 多 Agent 自由辩论房间、组织级共享 inbox、IM 主 UI。

### 1.2 目标

- 在 token 预算内提高**任务分解带宽**（深任务可分层，而不是把一切塞进主 context）。  
- 保持 **HITL / 确认 / 可追溯** 一等公民。  
- 与外部 Agent（Hermes / WorkBuddy）**联邦**，而不是把对方 runtime 嵌进来。

### 1.3 非目标

- 子 Agent 任意互聊、多轮互撕  
- 无限深度 / 无预算并行  
- 把对话地图改成「组织协作平台」  
- 恢复通用 `spawn_cli_agent` 多 provider 产品面

---

## 2. 三种路线（含取舍）

### 路线 A — 受控深树（推荐若一定要做）

- `MAX_SPAWN_DEPTH` 从 1 → **可配置 2**（硬顶 3，不可配置绕过）  
- 仅 `archetype ∈ {explore, plan}` 可再 spawn；`worker` / `verify` 仍为 leaf  
- 每层并行配额：`budget.parallel_per_level`（默认 2）  
- 全树总节点上限：`budget.max_nodes`（默认 7）  
- 冲突：父层 `synthesize`；可选一次 `verify`；歧义 `ask_user`

**优点：** 与现有 `spawn_subagent` / DelegationResult / pause 栈连续。  
**缺点：** 确认与 cancel 语义变复杂；需要 Turn / 地图表达多层。

### 路线 B — 工作流 DAG 当「静态树」

- 不增加 runtime 深度；用 F26 工作流节点表达树（AgentNode / Branch / HumanReview）  
- 运行时仍 depth=1；「树」是**设计时**拓扑

**优点：** 不碰 PRD 非目标；可观测、可复用模板。  
**缺点：** 不能动态「再拆一层」；对开放式探索弱。

### 路线 C — 联邦树（外树内浅）

- Lumina 永远 depth=1  
- 需要更深时：经 MCP/CLI 把整枝交给 Hermes/WorkBuddy（联邦，非内嵌）  
- 对方内部可有自家 swarm；Lumina 只收摘要 + status

**优点：** 对齐已落地 A（CLI 联邦）；风险隔离最好。  
**缺点：** 跨进程可观测性弱；确认边界在对方。

### 推荐组合

| 阶段 | 策略 |
|------|------|
| 现在 | **C 可走 MCP/CLI 联邦** + **B 已有**（工作流）+ **IDP 协议化浅树** |
| 若用户强需求「动态再拆」 | 再开 **A 的 depth=2 MVP**，单独改 PRD |
| 永不默认 | 辩论式 / 无限树 / 子↔子总线 |

---

## 3. 若实施路线 A：协议草案（IDP-Tree）

沿用委派信封，增加树字段：

```text
DelegationEnvelope
  goal: string
  archetype: explore|worker|verify|plan|custom
  depth: int                 # 当前节点深度（root=0）
  parent_run_id: string|null
  budget:
    max_depth: 2             # ≤ HARD_MAX_DEPTH(3)
    max_nodes_remaining: int # 向下递减
    parallel_cap: int
    token_cap: int | null
    round_cap: int
  return_schema: summary_only
  conflict_policy: parent_synthesize | ask_user | verify_once
  channel: parent_child_only  # 禁止 peer
```

生命周期（每节点）：

```text
spawn → running → (pause: confirm|ask_user)? → resume → result|fail|cancel
                 ↘ spawn_children? (仅当 depth < max_depth 且 archetype 允许)
```

**冲突解析（ConflictPolicy）：**

1. 多子摘要冲突标记 → 父 LLM `synthesize`（默认）  
2. 高风险分歧（写路径冲突 / 测试红绿矛盾）→ `ask_user`  
3. 可选叶子 `verify` **一次**，禁止 verify 再 spawn  

**禁止：**

- 子向兄弟发消息  
- verify/worker 再 spawn  
- 同 turn 无预算并行（必须扣 `max_nodes_remaining`）

---

## 4. 预算与 Token

| 旋钮 | 默认建议 | 说明 |
|------|----------|------|
| `HARD_MAX_DEPTH` | 3 | 代码硬限，配置不可突破 |
| `default_max_depth` | 2 | HarnessConfig |
| `max_nodes` | 7 | 含 root |
| `parallel_per_level` | 2 | 比现行 explore≤3 更紧（深度换宽度） |
| 回传 | 仅 `DelegationResult` 摘要 | 中间 tool 轨迹进 TraceStore，不进父 prompt |
| 便宜模型 | explore/plan 子树可走 cheap model（原 FR-28） | 树越深越必要 |

完成率实验（落地后必做）：同任务对比 `depth=1` vs `depth=2` 的 token、墙钟、确认次数、成功率。

---

## 5. HITL / 确认

- worker 写盘 / shell：沿用现有 confirm；**暂停整枝**（父 turn pause），避免兄弟继续写冲突  
- 地图节点：标注 `depth`、`run_id`、`waiting_confirm`  
- 取消：父 cancel → 递归 cancel 子进程/子 loop（需新 cancel fan-out）

---

## 6. 与 Hermes / WorkBuddy

```
Lumina Root (depth≤2 内树 或 depth=1)
   ├── in-process spawn_subagent …
   └── MCP/CLI external agent             → 外树（对方负责）
```

规则：

- **同一任务不要双开**：要么内树，要么外委，避免两边同时改同一 worktree  
- 外委默认 `--safe-mode` / worktree（Hermes POC 已支持参数）  
- Trace：外委只记 argv 摘要 + exit + stdout 截断；不伪造对方内部 span

---

## 7. UI（若做）

- 对话地图：树展开（已有子 Agent 树可复用），显示 depth badge  
- **不做**「Agent 聊天室」；人仍只跟 Root 对话  
- 工作流编辑器：可选导入「树模板」→ 静态 DAG（路线 B）

---

## 8. 里程碑（仅规划）

| 阶段 | 内容 | 依赖 |
|------|------|------|
| M0 | 本文 + 评估会议 | — |
| M1 | PRD 修订：允许可配置 depth≤2；保留禁止辩论 | 产品拍板 |
| M2 | `SpawnContext.depth` 放宽 + budget 扣减 + 测试 | M1 |
| M3 | 地图 depth / cancel fan-out | M2 |
| M4 | eval：树 vs 浅树完成率 | M3 |
| — | **明确不做**：peer bus、辩论、depth>3 | 持续 |

---

## 9. 决策建议（给未来的自己）

| 信号 | 行动 |
|------|------|
| 用户痛点主要是「Hermes 有技能我要用」 | **停在联邦 C**（MCP/CLI，不嵌入 runtime） |
| 痛点是「主 Agent context 爆、需要再拆一层 explore」 | 考虑 **A depth=2** |
| 痛点是「可复现流水线」 | 加强 **B 工作流**，别上 swarm |
| 面试要讲协作 | 讲 **约束型树 + 联邦**，别讲「我们做了 swarm 平台」 |

**默认结论：** 树状 swarm **可设计、可试点 depth=2**，但不应作为 Lumina 产品主叙事；优先把联邦与工作流用熟，再决定是否碰 PRD 硬限。

---

## 10. 开放问题（落地前必须答）

1. depth=2 时，子 explore 再 spawn 的并行配额如何与现行 `MAX_PARALLEL_EXPLORE=3` 统一？  
2. worker 在 depth=1 写 worktree 时，depth=2 兄弟是否允许共享 worktree？  
3. 外委 Hermes 与内树同时存在时，文件锁 / git worktree 策略？  
4. 企业审计：多层树的 Trace 关联键用 `root_trace_id` 还是每节点独立？

---

*End of design — no implementation attached.*
