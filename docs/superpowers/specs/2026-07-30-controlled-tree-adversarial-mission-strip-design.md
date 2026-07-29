# 受控深树 · 结构化对抗 · Mission Strip（设计稿）

**日期：** 2026-07-30  
**状态：** Spec approved for planning — 实施前按本文件改 PRD，再开 implementation plan  
**关联：** [PRD.md](../../PRD.md) · [tree-swarm](2026-07-27-tree-swarm-agent-design.md) · [IDP](2026-07-27-idp-design.md) · [workflow-dag-design.md](../../workflow-dag-design.md)

---

## 0. 决策摘要

采用 **方案 1：双引擎 + 共享 WriteGate**。

| 维 | 决策 |
|---|---|
| 拓扑 A | 受控深树：`max_depth` 可配到 2，硬顶 3 |
| 拓扑 B | 工作流静态树：沿用现有 Skill DAG（优先承接可复现流水线） |
| 设置 | 全局默认 + 单次覆盖；`adversarial` 可叠在深树或 DAG 上 |
| 对抗形态 | 结构化交替发言（共享辩词），**非**自由 peer 总线 / 聊天室 |
| 对抗触发 | `auto`：高分歧或高风险写路径；亦支持 `force` / `off` |
| 轮次 | 默认 6，硬顶 12；**评审仲裁可提前结束** |
| 写盘 | 子 Agent 仅 `.lumina/proposals/{run_id}/`；正式路径只经 **项目落地**（裁判/编排收尾 + HITL） |
| UI | Mission Strip：岗位中文名 + 真进度条；点击展开思考；对抗时独立左右面板 |

**产品用语：** 主叙事仍是 harness · 委派 · 确认 · 地图 · 工作流。可用「编制 / 岗位」描述 Mission Strip；**不以**「Agent 协作平台 / 自由 Swarm」定位。

---

## 1. 设置与拓扑模型

### 1.1 两维旋钮（可叠加）

| 维 | 取值 | 说明 |
|---|---|---|
| `topology` | `shallow` · `deep_tree` · `workflow` | 执行拓扑；出厂默认 `shallow` |
| `adversarial` | `off` · `auto` · `force` | 结构化对抗；出厂建议 `auto` |

### 1.2 生效顺序

1. 会话 / 单次请求覆盖（若有）  
2. 否则 `~/.lumina/agent.json` → `harness` 全局默认  
3. 硬顶不可配置绕过：`HARD_MAX_DEPTH=3`、对抗轮次 ≤12、子不可自由 peer 总线

### 1.3 深树预算（topology=`deep_tree`）

| 旋钮 | 默认 | 硬顶 / 说明 |
|---|---|---|
| `default_max_depth` | 2 | ≤ `HARD_MAX_DEPTH`（3） |
| `max_nodes` | 7 | 含 root |
| `parallel_per_level` | 2 | 深度换宽度 |
| 可再 spawn | 仅 `explore` / `plan` | `worker` / 正反 / 裁判均为 leaf |

`topology=shallow` 时行为与现行一致：`MAX_SPAWN_DEPTH=1`。

### 1.4 与工作流

- `topology=workflow`：走现有 DAG；深度由图决定，不靠 runtime 再拆。  
- `adversarial` 叠上时：插入或跳转 `adversarial_review` 子图，状态同步到同一套辩论 UI 与 Mission Strip。

---

## 2. WriteGate（防打架写盘）

### 2.1 原则

业务路径与可执行落地 **只允许** 项目主管收尾或评审仲裁 → **项目落地** 在 HITL 确认后写入。  
正方 / 反方 / 调研 / 执行者 **不得** 直接改业务文件。

### 2.2 权限矩阵

| 角色（内部码） | 读业务 | 写 proposals | 写业务路径 | Shell |
|---|---|---|---|---|
| `pro` / `con` | ✓ | ✓ | ✗ | 默认关；可选只读探测 |
| `explore` / `plan` | ✓ | ✓ | ✗ | 按 archetype |
| `worker` | ✓ | ✓ | ✗ | 需确认；目标须在 proposals |
| `referee` / `root` 收尾 | ✓ | ✓ | ✓（经确认） | 沿用 confirm |
| 人 | — | — | 可改判 / 拒绝落地 | — |

### 2.3 收尾流水线

```
交替辩词 + proposals 草稿
  → 评审仲裁 synthesize（可提前结束，或打满 6/12）
  → 落地预览（路径 diff / 补丁列表）
  → HITL 确认
  → WriteGate.apply → 业务路径
```

### 2.4 冲突

- 两侧草稿改同一逻辑文件 → 仲裁必须二选一、合并，或 `ask_user`；禁止静默覆盖。  
- 对抗进行中：业务路径 WriteGate **锁闭**。  
- 取消对抗：丢弃未确认落地；proposals 可保留供追溯。

### 2.5 IDP 扩展

- `channel = debate_transcript`（交替发言，非 peer bus）  
- `conflict_policy ∈ {referee_synthesize, ask_user, parent_synthesize, verify_once}`  
- 工具层：子 `file_write` jail 到 `~/.lumina/proposals/{run_id}/`（或工作区等价前缀）；越狱返回 error。

---

## 3. 结构化对抗

### 3.1 形态

- **交替发言 + 共享辩词**：正 → 反 → 正…；各方可见 transcript 上一轮。  
- **不是** 子↔子任意互发工具总线，也不是第三聊天会话。  
- 人仍只与 **项目主管** 对话；辩论 UI 为观察 + HITL。

### 3.2 触发（`adversarial=auto`）

命中任一即进入辩论相位与独立 UI：

1. 高风险写路径：即将对业务路径批量改 / 删除等，变更面 ≥ 阈值（默认 ≥2 文件或含删除）。  
2. 高分歧：多路摘要路径冲突、结论互斥、测试红绿矛盾。  
3. 显式：用户或主管要求「正反辩一下」→ 等价 `force`。

`off`：永不自动开。`force`：跳过启发式。

### 3.3 轮次

| 项 | 值 |
|---|---|
| 默认 | 6 |
| 硬顶 | 12 |
| 提前结束 | 评审仲裁判定信息已够（优先于打满） |
| 「再开一轮」 | 人可要求，仍受硬顶约束 |

### 3.4 叠在深树上

```
项目主管
├── (可选) 调研/产品经理 深树 depth≤2
└── [触发] DebatePhase
      ├── 方案主张  ←→  风险质询   （交替，共享 transcript）
      └── 评审仲裁 → 项目落地
```

辩论进行中：深树兄弟暂停写业务；可读、可写 proposals。

### 3.5 叠在 DAG 上

可选子图模板 `adversarial_review`：主张/质询交替节点 → 评审仲裁 → HumanReview → 落地节点。  
`auto` 时在进入高风险写节点前插入或跳转。

---

## 4. Mission Strip UI

### 4.1 反模式（相对 Kimi 式）

| 不做 | 做 |
|---|---|
| 拟人昵称 + 像素头像 | 固定**岗位中文名** |
| 聊天室主界面 | 编制条 + 独立辩论面板 |
| 假百分比空转 | 阶段映射真进度；未知则 indeterminate pulse |

### 4.2 岗位显示名

| 内部码 | UI 显示名 | 职责 |
|---|---|---|
| `root` | 项目主管 | 拆任务、收口、对人说话 |
| `plan` | 产品经理 | 定方案边界与验收 |
| `explore` | 调研分析 | 只读摸清现状；并行：`调研分析 · 1` |
| `worker` | 执行者 | 只写提案草稿 |
| `pro` | 方案主张 | 辩论正方 |
| `con` | 风险质询 | 辩论反方 |
| `referee` | 评审仲裁 | 够信息则收束并合成 |
| `write_gate` | 项目落地 | 确认后写入正式路径 |

主 UI 只显示岗位名；设置/调试可看内部码。

### 4.3 Strip 布局

```
┌─ 任务条 · <goal 摘要> ──── topology · adversarial 状态 ──┐
│  项目主管   ████████░░░░  综合中           进行中        │
│  调研分析·1 ████████████  扫描代码库       完成          │
│  方案主张   ██████░░░░░░  第 3/6 轮        发言中        │
│  风险质询   ░░░░░░░░░░░░  等待             待命          │
│  评审仲裁   ░░░░░░░░░░░░  —               待命          │
│  项目落地   ░░░░░░░░░░░░  闸门锁定         锁定          │
└──────────────────────────────────────────────────────────┘
```

### 4.4 点击展开

单击行 → 展开/收起：

- 思考摘要（长文可再折叠）  
- 工具步骤时间线  
- proposals 草稿路径  
- Trace / 模型原文入口（复用 FR-51）

**方案主张 / 风险质询：** 展开看本轮辩词与思考；另提供入口进入左右辩论面板。  
**项目落地：** 展开看 diff 预览与确认状态。

### 4.5 独立辩论 UI（对抗启动时）

```
┌─ 议题 · 轮次 n/max · 状态 ─────────────────────────────┐
├─────────────────────┬───────────────────────────────────┤
│ 方案主张            │ 风险质询                          │
│ 辩词流（交替）      │ 辩词流（交替）                    │
│ 思考可展开          │ 思考可展开                        │
├─────────────────────┴───────────────────────────────────┤
│ 评审仲裁：分歧点 · 合成 · 落地预览                       │
│ 人：采纳 / 改判 / 再开一轮（≤硬顶） / 取消               │
└─────────────────────────────────────────────────────────┘
```

### 4.6 进度映射

| 相位 | 进度来源 |
|---|---|
| 委派节点 | `spawn → tool_loop → summary → done` |
| 辩论 | `round / max_rounds`；仲裁提前结束则跳满 |
| 项目落地 | `locked → preview → confirming → applied` |
| 未知耗时 | indeterminate pulse（禁止假 %） |

数据：SSE / `idp_update` 扩展字段 `role · display_name · status · progress · phase`。

### 4.7 动效纪律

- 活跃行：左侧 2px 角色色 + 条内单次微光扫过  
- 完成：细线 + 完成标记  
- 失败：警示色 + 可点错误摘要  
- 禁止彩虹、彩带、像素脸

---

## 5. PRD 修订清单（本规格要求）

1. **Shallow tree** → 改为 **Controlled tree**：默认 shallow；可配 deep_tree depth≤2，硬顶 3。  
2. **禁止「自由辩论 / peer 总线 / 无限互撕」**；允许 **结构化对抗**（交替辩词 + 评审仲裁 + WriteGate）。  
3. 委派模型图：补充深树预算、对抗相位、WriteGate。  
4. Roadmap：新增 FR（建议编号）  
   - **FR-53** WriteGate + proposals jail  
   - **FR-54** 可配深树 depth≤2  
   - **FR-55** 结构化对抗（auto/force/off，轮次 6/12）  
   - **FR-56** Mission Strip + 辩论独立 UI  
5. Open Decisions：子拓扑与「无辩论」条目按上表更新。  
6. 用语：不以 Swarm 平台定位；Mission Strip / 岗位编制可用于 UI 文案。

---

## 6. 里程碑（实施顺序）

| 阶段 | 内容 | 依赖 |
|---|---|---|
| M0 | 本文 + PRD 修订 | — |
| M1 | WriteGate + proposals jail + 测试 | M0 |
| M2 | deep_tree depth=2 + budget + cancel fan-out | M1 |
| M3 | 结构化对抗协议 + 轮次/仲裁提前结束 | M1 |
| M4 | Mission Strip（岗位名 + 进度 + 展开思考） | M2/M3 SSE |
| M5 | 辩论独立 UI（左右 + 仲裁区） | M3 + M4 |
| M6 | DAG `adversarial_review` 模板 + 设置旋钮 | M3 |
| M7 | eval：shallow vs deep vs adversarial token/成功率 | M2–M5 |

---

## 7. 非目标（本规格）

- 自由 peer 总线 / IM 式 Agent 聊天室作主 UI  
- 像素头像与拟人昵称  
- depth > 3 或无预算并行  
- 恢复通用 `spawn_cli_agent`  
- 子 Agent 直写业务路径  

---

## 8. 开放问题（实施计划阶段收口）

1. proposals 根：全局 `~/.lumina/proposals/` vs 工作区 `.lumina/proposals/`（建议工作区优先，全局作无 workspace 回退）。  
2. `auto` 变更面阈值是否进 HarnessConfig（建议是）。  
3. worker 在 deep_tree 下是否完全禁止业务写（本规格：**是**，一律经落地）。  

---

## 9. Spec self-review

| 检查 | 结果 |
|---|---|
| Placeholder | 无 TBD；开放问题集中在 §8 |
| 内部一致 | 轮次 6/12、WriteGate、岗位名与 §1–4 一致 |
| 范围 | 单规格可拆 M1–M7；适合一份 implementation plan |
| 歧义 | 「对话」= 交替共享辩词，已钉死非 peer bus |

---

*End of design.*
