# Skill DAG 工作流设计

**日期：** 2026-07-09
**状态：** 设计待审

## 1. 概述与目标

为 Lumina 增加工作流编辑器能力：让用户能把 skill/agent 节点拖拽编排成有向无环图，保存为可复用工作流并一键运行。分支地图与工作流在技术层共享画布组件，但在产品层拆开入口（分支地图留对话内，工作流独立 tab）。

核心分层原则：**DAG 管「做什么、什么顺序」，节点管「怎么做」**。调度器层面是确定性拓扑执行，不请 LLM 路由；节点内部可按需运行 AgentLoop 做 ReAct 推理。

## 1.5 DAG 模型：分支地图与工作流的关系

分支地图和工作流在结构上同构——都是有向无环图。差异在节点类型、I/O 端口数、执行模型和语义归属。本设计在**技术层共享画布组件**，但在**产品层拆开入口**——两者不合并为同一个 tab。

| 维度 | 分支地图 | 工作流 |
|------|----------|--------|
| 语义归属 | 属于某个对话线程 | 独立顶层对象 |
| 节点类型 | chat_turn | skill / agent / branch |
| 输入端口 | 单（树形，一父） | 多（汇合） |
| 输出端口 | 多（fork） | 多（扇出） |
| 执行模型 | 交互式，沿 active path 单步 | 批处理，拓扑排序一口气跑完 |
| 触发方式 | 用户在每个节点打字 | `/run` 或编辑器「运行」按钮 |
| 数据来源 | 对话历史（retrospective） | 工作流定义（prospective） |
| 编辑能力 | 基本只读 + fork/rollback | 全编辑（拖拽/连线/配置） |

**技术共享**：Drawflow 画布作为可复用内部组件（缩放/平移/选中检视/边连线/主题样式），被分支地图和工作流编辑器各自使用。

**产品分离**：分支地图留在对话内（该对话的一个视图），工作流独立成 tab。理由：两者心智模型不同（"回看这个对话" vs "设计要跑的流程"），合并会引入数据源切换的认知负担。

**未来融合点**：node kind 走注册表，未来工作流可接 chat_turn 节点做人工评审，对话可在分叉点挂工作流节点做自动处理——混合编排零侵入。

## 2. 约束

- 轻量：不引入 LangGraph / Prefect 等重型编排框架。
- LLM 隔离：调度器本身不调 LLM；LLM 只在 AgentNode / BranchNode(agent 模式) 内部被调用。
- 不复用 Hermes 组件。
- v1 只做 SkillNode + AgentNode + BranchNode，节点接口预留扩展。

## 3. 架构

```
┌─────────────── Electron Desktop ───────────────┐
│  Workflow Editor (webview, Drawflow)            │
│   左:节点面板  中:画布  右:节点配置              │
└───────────────────┬─────────────────────────────┘
                    │ /api/workflows (save/run/list)
┌───────────────────▼─────────────────────────────┐
│              FastAPI Backend                      │
│  WorkflowStore  WorkflowScheduler  NodeExecutors │
│   (JSON 持久化)   (拓扑排序+分支)   (skill/agent)  │
└───────────────────┬─────────────────────────────┘
                    │ 复用
        ┌───────────┼───────────┐
        ▼           ▼           ▼
  ExecutableSkill  AgentLoop   ProgressHub
   (run.py)        (TurnOrch)  (SSE 事件)
```

## 4. 节点模型

### 4.1 NodeExecutor Protocol

所有节点执行器实现统一协议，走注册表，方便扩展：

```python
class NodeExecutor(Protocol):
    kind: str
    def execute(self, spec: NodeSpec, inputs: dict, ctx: NodeContext) -> NodeResult: ...
    def output_schema(self, spec: NodeSpec) -> dict: ...
```

`NodeExecutorRegistry` 按 `kind` 分发。未来加 `"tool"` / `"prompt_skill"` 只需注册新 Executor。

### 4.2 NodeSpec

```python
@dataclass
class NodeSpec:
    id: str
    kind: str            # "skill" | "agent" | "branch"
    config: dict         # kind 相关配置
    inputs_schema: dict  # 期望的输入 JSON schema
    outputs_schema: dict # 产出的输出 JSON schema
    on_failure: str = "stop"  # "stop" | "continue"
```

### 4.3 v1 节点

**SkillNode** (`kind="skill"`)
- 激活现有 ExecutableSkill 的 `execute()`（当前为死代码）。
- `config`: `{ skill_name, version }`
- 子进程执行 `run.py`，stdin 喂 JSON inputs，stdout 读 JSON outputs。
- 超时上限 120s（沿用现有 ExecutableSkill 配置）。

**AgentNode** (`kind="agent"`)
- 内部起临时 AgentLoop（复用 TurnOrchestrator.run_agent_turn）。
- `config`: `{ prompt_template, archetype?, tools?, output_format: "text"|"json" }`
- prompt_template 支持变量插值 `{{upstream.field}}`。
- AgentLoop 拿到 prompt + 上游数据后 ReAct 推理，产出结构化输出。
- 若内部调写类工具，复用现有 FileAuthService 确认门控。

**BranchNode** (`kind="branch"`)
- 条件路由，走某一输出端口，调度器只追该端口的下游边。
- `config`:
  ```json
  {
    "condition": { "type": "expr" | "agent" },
    "ports": ["port_a", "port_b"]
  }
  ```
- `expr` 模式：简单表达式（JSON-path 相等 / 包含判断），确定性。
- `agent` 模式：跑一个 AgentLoop 判定走哪个端口（灵活但调 LLM）。

## 5. 调度器

`WorkflowScheduler` 纯 Python，不调 LLM：

1. 加载工作流 JSON → 解析 nodes + edges。
2. 拓扑排序确定执行顺序。
3. 对每个节点：
   - 收集上游 outputs，按 `inputs_schema` 字段名映射 + 类型校验。
   - 通过 Registry 取对应 NodeExecutor 执行。
   - 发 `node_started` / `node_finished` / `node_failed` 进度事件。
   - BranchNode 执行后只激活匹配端口的下游边。
4. 失败处理：按节点 `on_failure`（默认 stop 中止整条流；continue 则跳过该节点继续）。
5. 扇出：一个节点输出可喂多个下游。汇合：多上游输出合并为 dict 喂下游。

v1 支持的结构：线性链、扇出、汇合、条件分支。不支持循环（DAG 定义）。

## 6. 工作流格式

存 `~/.lumina/workflows/<name>.json`：

```json
{
  "name": "search-and-summarize",
  "version": 1,
  "inputs_schema": { "topic": { "type": "string" } },
  "outputs_schema": { "summary": { "type": "string" } },
  "nodes": [
    {
      "id": "n1",
      "kind": "skill",
      "config": { "skill_name": "web_search" },
      "inputs_schema": { "query": "string" },
      "outputs_schema": { "results": "array" },
      "on_failure": "stop"
    },
    {
      "id": "n2",
      "kind": "agent",
      "config": { "prompt_template": "总结这些结果：{{n1.results}}" },
      "inputs_schema": { "n1.results": "array" },
      "outputs_schema": { "summary": "string" }
    }
  ],
  "edges": [
    { "from": "n1", "to": "n2", "port": "default" }
  ]
}
```

运行日志落 `~/.lumina/workflows/runs/<run_id>.json`：每个节点的输入输出、耗时、状态。

## 7. IA 与 Shell 重构

### 7.1 顶级 Shell

加入一条顶级左侧导航栏（图标），两个一等公民模式 + 左下角设置入口：

- **对话**：聊天列表 + 聊天视图（现有功能沿用），视图内含「分支地图」切换按钮
- **工作流**：工作流列表 + 编辑器
- **设置**（左下角齿轮）：账户/权限/MCP/导入等，不占导航位

理由：导航项只放高频且并列的功能模式；设置是低频配置入口，放左下角齿轮一键可达但不与高频功能并列。分支地图语义上属于某个对话，留对话内最自然。

### 7.2 分支地图（对话内视图）

- 打开方式：对话内「查看分支地图」按钮（沿用现有入口）
- 节点 = chat_turn，只读展示对话历史分叉
- 可在节点上「重启对话分叉」（沿用现有 fork/rollback/restore）
- 交互式执行：选中 active path 末端节点继续对话
- 画布使用共享的 Drawflow 画布组件

### 7.3 工作流编辑器（独立 tab）

- 打开方式：导航「工作流」tab → 工作流列表 → 选/新建
- 节点 = skill / agent / branch，可拖拽编辑
- 左侧节点面板（已安装 skill + Agent 节点 + Branch 节点）
- 右侧选中节点 schema/参数配置
- 保存→写 `~/.lumina/workflows/<name>.json`
- 运行→调 `/api/workflows/run`，画布实时高亮当前执行节点（接 SSE）
- 画布使用共享的 Drawflow 画布组件

### 7.4 共享画布组件

Drawflow 画布作为可复用内部组件，提供：缩放/平移、节点选中检视、边连线交互、主题样式。分支地图和工作流编辑器各自实例化它，传入不同的节点渲染器和交互回调。

### 7.5 对话 ↔ 工作流互联

- 对话内 `/run <name> {json}` → 后端调度工作流 → 结果回流聊天消息
- 工作流编辑器「发送结果到对话」→ 创建新对话 thread，把工作流输出作为首条 user 消息
- 未来：工作流末尾接 chat_turn 节点做人工评审（混合模式）

## 8. 触发与 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/workflows` | GET | 列出已保存工作流 |
| `/api/workflows/{name}` | GET | 读取工作流 JSON |
| `/api/workflows/{name}` | PUT | 保存/更新工作流 |
| `/api/workflows/{name}` | DELETE | 删除工作流 |
| `/api/workflows/{name}/run` | POST | 运行工作流，body 为 inputs JSON，返回 run_id + SSE 流 |

聊天触发：`/run <name> {json}` 命令 → 后端调度 → 结果回聊天。

## 9. 进度与错误处理

- 复用 ProgressHub，新增事件类型：`node_started` / `node_finished` / `node_failed` / `workflow_completed`。
- 每个 NodeExecutor 执行时发事件，前端编辑器 + 聊天都可订阅。
- AgentNode 内的确认门控走现有 FileAuthService，确认时整条工作流暂停（复用 SessionStore pause 机制）。
- 节点超时 / 异常：记录到 run 日志，按 `on_failure` 决定中止或继续。

## 10. 测试策略

- **Scheduler 单测**：拓扑排序、schema 映射、扇出汇合、条件分支路由、on_failure 策略。
- **NodeExecutor 单测**：SkillNode（mock subprocess）、AgentNode（mock TurnOrchestrator）、BranchNode（expr + agent 模式）。
- **WorkflowStore 单测**：保存/读取/删除/版本。
- **E2E**：两节点工作流（skill → agent 总结）端到端跑通；条件分支工作流走对端口。

## 11. 未来扩展

- `ToolNodeExecutor`：把现有工具（search_files/patch/shell/记忆）做成节点。
- `PromptSkillNodeExecutor`：把 PromptSkill 从纯提示词改造为可执行。
- 循环 / 重试节点。
- 工作流版本管理与导入导出。
- 子工作流节点（工作流嵌套）。

## 12. 工作流封装为 Skill 与暂停能力（v2 候选，v1 不实现）

### 12.1 工作流作为 Skill

工作流可封装为单一 skill，获得双重身份：
- 在工作流 tab：可编辑的 DAG
- 在对话或其他工作流中：可调用的单一 skill 节点（`WorkflowNode`，kind 注册进 NodeExecutorRegistry）

封装要求：工作流定义声明完整的 inputs_schema / outputs_schema，对外只暴露这两个接口，内部 DAG 结构对调用方透明。这天然支持工作流嵌套（子工作流）。

### 12.2 暂停能力

工作流暂停 = 执行权交回外部（对话/用户），等输入后恢复。现状两种执行模型：对话（ReAct，工具确认时已能暂停）和工作流（拓扑批处理，一口气跑完，不能暂停）。

**三条路径，按复杂度递增：**

**路 1：节点级暂停（推荐 v2 首选）**
- 不改工作流执行模型，只在 AgentNode 内部复用现有确认门控（FileAuthService）。
- AgentNode 跑 AgentLoop → 调写工具 → 确认门控暂停 → 工作流阻塞等待该节点 → 节点恢复 → 工作流继续。
- 暂停粒度 = 节点；工作流调度器本身不感知"被暂停"，只是某节点执行时间长。
- 复杂度低：复用现有 SessionStore pause 机制，调度器仅 `await` 节点结果。
- 能封装成 skill：工作流对外暴露 schema，内部暂停对调用方透明。

**路 2：显式 PauseNode + 用户输入节点（v3 候选）**
- 工作流里可放"暂停问用户"节点，整个工作流进入 paused 状态，外部答完恢复。
- 需工作流级状态机（running/paused/completed/failed）+ 持久化中间上下文 + 恢复 API。
- 复杂度中高。

**路 3：协程式交织执行（不推荐）**
- 工作流和对话完全交织，任意点互相交接。
- 复杂度高，接近被否的 LangGraph 量级，违背轻量约束。

### 12.3 v1 边界

v1 不实现任何暂停能力，工作流为一口气跑完的批处理。封装为 skill 也不在 v1（v1 只做独立 tab 的编辑器 + `/run` 触发）。暂停和封装均标注为 v2 候选，待 v1 跑通后按实际需求推进。
