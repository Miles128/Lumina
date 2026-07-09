# 对话树状分支（Tree Branching）Spec

## Why

当前对话是「扁平分页」：每个 thread 内 `messages` 是无 ID 的线性数组（`{role, text}`），用户无法在某个节点重启对话、产生分叉，也无法回溯不同思路。用户希望把对话细化成树状（甚至 DAG）图，能在任意节点「开新分支」继续，像 ChatGPT 的 fork-from-message 一样探索不同方向。

## 推荐方案（一句话）

把 thread 内每条消息建模为带稳定 `id` + `parent_id` 的**树节点**（单父，语义即树；数据结构不阻断未来扩展为 DAG），用 `active_leaf_id` 记录当前展示路径，fork = 以某祖先消息为 `parent_id` 发新消息，兄弟分支用 `<` `>` 切换；再提供一棵可视化「对话地图」做总览与跳转。

### 关键设计决策

- **树优先，DAG 留待后续**：每条消息单一 `parent_id`。多父合并（merge branches）语义复杂、UX 成本高，按「聚焦核心、最小实现」原则暂不做；单 `parent_id` 不妨碍日后升级为 `parent_ids` 列表。
- **thread 仍是顶层容器**：分支发生在 thread 内部，不同 thread 仍是独立话题。保留侧边栏 thread 列表心智模型不变。
- **消息级分支**（非 turn 级）：可从任意一条消息 fork，粒度最细，与 ChatGPT 一致。
- **active path 用 leaf 表达**：thread 记 `active_leaf_id`，当前路径 = 从 leaf 沿 `parent_id` 回溯到 root 再反转。切换兄弟 = 改 `active_leaf_id`。比「每个节点存 active_child」更简单。
- **agent_history 走 active path**：LLM 上下文 = root→active_leaf 的消息序列，行为与现状一致，只是来源从「flat slice」变成「路径回溯」。

## What Changes

- **消息节点化**：`ChatThread.messages` 每条增加 `id`（uuid）、`parent_id`（前一条 id 或 `""`）。**BREAKING**（内部 schema 变更，需迁移）
- **active path**：thread 增加 `active_leaf_id`；`agent_history` / 渲染按路径回溯。
- **fork 能力**：`POST /api/chat` 接受可选 `parent_message_id`；fork 时新 user 消息以指定祖先为父。
- **兄弟导航**：消息有多个子时，UI 显示 `<` `>` 切换 active leaf。
- **对话地图视图**：新增 thread 内消息树的可视化（节点=消息，边=父子），点击节点跳转/设为 active leaf。
- **迁移**：旧的扁平 `messages` 自动补 `id`+`parent_id`（链式）与 `active_leaf_id`（末条）；前端 localStorage 同步迁移。

## Impact

- 受影响代码：
  - [chat_threads.py](file:///Users/sihai/Documents/My Projects/Lumina/src/secretary/services/chat_threads.py) — 消息 schema、`append_turn`、`agent_history`、`replace_all`、迁移
  - [chat_service.py](file:///Users/sihai/Documents/My Projects/Lumina/src/secretary/agent/chat_service.py) — `_load_history`、`_append_history`、`reply` 透传 `parent_message_id`
  - [app.py](file:///Users/sihai/Documents/My Projects/Lumina/src/secretary/api/app.py) — `ChatRequest` 加 `parent_message_id`；新增分支切换 / 树视图接口
  - [chat.js](file:///Users/sihai/Documents/My Projects/Lumina/desktop/ui/chat.js) — 消息 ID、fork 按钮、兄弟导航、发送带 `parent_message_id`、地图视图
  - [chat.css](file:///Users/sihai/Documents/My Projects/Lumina/desktop/ui/chat.css) / [index.html](file:///Users/sihai/Documents/My Projects/Lumina/desktop/ui/index.html) — 分支 UI 样式与地图容器
  - [graph.js](file:///Users/sihai/Documents/My Projects/Lumina/desktop/ui/graph.js) — 仅作画布模式参考，地图视图用独立模块
- 受影响测试：`tests/services/test_chat_threads.py`、`tests/agent/test_chat_service.py`、`tests/api/test_app.py`、`tests/e2e/test_ui_playwright.py`

## ADDED Requirements

### Requirement: 消息节点化与父子关系
系统 SHALL 为 thread 内每条消息分配稳定 `id`（uuid 短串）与 `parent_id`（指向上一条消息 id，root 为 `""`），使消息构成一棵树。

#### Scenario: 新对话首条消息
- **WHEN** 用户在空 thread 发送第一条消息
- **THEN** 该消息 `id` 为新生成 uuid，`parent_id` 为 `""`，并成为 `active_leaf_id`

#### Scenario: 正常续接（无分叉）
- **WHEN** 用户在当前 active leaf 之后正常发送消息
- **THEN** 新消息 `parent_id` = 当前 `active_leaf_id`，并更新为新的 `active_leaf_id`

### Requirement: 在任意节点开新分支（fork）
系统 SHALL 允许用户从 thread 内任意一条已有消息发起分支：新消息以该消息为 `parent_id`，原分支保留。

#### Scenario: 从历史消息 fork
- **WHEN** 用户点击某条非 leaf 的历史消息「从这里新开分支」并发送新消息
- **THEN** 新消息 `parent_id` = 该历史消息 id；该历史消息现有子分支不被删除；`active_leaf_id` 更新为新消息产生的叶子；UI 切换到新分支

#### Scenario: 兄弟分支切换
- **WHEN** 某消息存在多个子分支且用户点击 `<` / `>`
- **THEN** `active_leaf_id` 更新为对应兄弟子树的最深叶子；消息列表按新 active path 重渲染

### Requirement: active path 驱动上下文与渲染
系统 SHALL 以 `active_leaf_id` 为准，沿 `parent_id` 回溯到 root 确定当前路径，用于 LLM history 与 UI 渲染。

#### Scenario: agent_history 返回路径消息
- **WHEN** ChatService 为 LLM 组装历史
- **THEN** 返回 root→active_leaf 的有序消息（受 `MAX_HISTORY_MESSAGES` 截断），而非旧的扁平 slice

### Requirement: 对话地图视图
系统 SHALL 提供线程内消息树的可视化总览：节点=消息（区分 user/assistant），边=父子关系；点击节点跳转并设为 active leaf。

#### Scenario: 打开地图
- **WHEN** 用户在 thread 内切换「地图」视图
- **THEN** 以层级树布局渲染该 thread 全部消息节点与边；当前 active path 高亮

### Requirement: 旧数据迁移
系统 SHALL 自动迁移既有扁平 `messages`：按顺序补 `id`、链式 `parent_id`，`active_leaf_id` 设为末条消息 id；前端 localStorage 同步迁移。

#### Scenario: 加载旧 thread
- **WHEN** 读取到无 `id` 字段的旧 `messages`
- **THEN** 顺序生成 id、`parent_id` 指向上一条、首条 `parent_id=""`、`active_leaf_id`=末条 id，并写回

## MODIFIED Requirements

### Requirement: 消息持久化与展示
原：`messages` 为 `{role,text}` 扁平数组，`append_turn` 末尾追加，`agent_history` 取末 N 条。
改：`messages` 为 `{id,parent_id,role,text,timestamp?}` 节点数组；`append_turn` 支持指定 `parent_message_id`（默认当前 active leaf）；`agent_history` 走 active path；新增 `set_active_leaf(thread_id, leaf_id)` 与 `thread_tree_view(thread_id)`。

## REMOVED Requirements

### Requirement: 扁平消息数组语义
**Reason**: 被树节点模型取代。
**Migration**: 见「旧数据迁移」要求；读取时自动补全 id/parent_id，向后兼容。

---

## 补充：LangGraph 可行性评估

> 用户追加问题：「分析用 langgraph 是否可行」。本节评估是否引入 LangGraph（LangChain 生态的状态机/检查点框架）来实现上述树状分支。

### 概念对齐（避免混淆两套树）
本项目存在两套"树"，本 spec 只动第二套：
- **turn 内部树** = 一次用户消息 → Agent Loop 内部派生子 agent（explore/worker/verify）。已存在：[turn_models.py](file:///Users/sihai/Documents/My%20Projects/Lumina/src/secretary/agent/turn_models.py) 的 `TurnContext.parent_turn_id` / `child_id`，[session_store.py](file:///Users/sihai/Documents/My%20Projects/Lumina/src/secretary/agent/session_store.py) 持久化。
- **对话轮次树/DAG（本 spec 目标）** = 人机交互消息层面的分叉，每条 message 是节点。

### LangGraph 提供的相关能力
- **Checkpoint 持久化**：每个 super-step 保存状态，`Checkpoint` 含 `parent_config` 形成链式结构
- **`thread_id` + `checkpoint_id` fork**：传入历史 `checkpoint_id` + 新 `thread_id` 即可"从历史点创建分支"（官方支持）
- **StateGraph + reducer**：消息列表可声明 `add_messages` reducer 自动 append
- **interrupt**：原生 human-in-the-loop 暂停/恢复，与本项目 `PendingConfirmation` 语义对齐

### 契合度评估

| 维度 | LangGraph | 本项目现状/约束 | 契合度 |
| --- | --- | --- | --- |
| 对话分叉 | `checkpoint_id` fork 原生支持 | 节点级 fork | ✅ 高 |
| 持久化 | SQLite/Memory checkpointer 开箱即用 | JSON 文件 | ⚠️ 引入新依赖 |
| LLM 编排 | 强依赖 LangChain 抽象（`BaseChatModel`、`add_messages`） | **硬约束：移除 LLM 相关组件，LLM 调用由 agent 外部处理** | ❌ 冲突 |
| 工具调用 | `ToolNode` / prebuilt | 已有自研 `Tool` 基类 + `ChatToolRegistry` + subagent 派生 | ❌ 重复 |
| 流式输出 | `astream_events` | 已用 `chat_completion(on_delta=...)` | ⚠️ 需改造 |
| 体积 | langgraph + langchain-core 依赖较重 | 明确要"保持产品轻量" | ❌ 违背 |

### 结论：不引入 LangGraph（技术可行，工程不推荐）

1. **硬约束冲突**：[user_profile.md](file:///Users/sihai/.trae-cn/memory/user_profile.md) 明确要求"LLM-related components should be completely removed, with LLM calls handled externally by the agent"。LangGraph 是 LLM 编排框架，核心抽象（StateGraph、Checkpointer、reducer）都围绕 LangChain 的 message/模型设计，引入它等于把 LLM 框架重新塞回项目。
2. **过度抽象**：本 spec 真正需要的只是"消息节点带 `parent_id` + 路径回溯"——约 200 行代码（见上方 Task 1-2）。LangGraph 带来的 StateGraph 编译、reducer 机制、super-step 调度都是本项目用不到的复杂度。
3. **重复造轮子**：本项目已有 `TurnContext` 父子树、`ChatToolRegistry`、`SubAgentResumeState` 暂停恢复——这些与 LangGraph 的 checkpoint/interrupt 功能重叠，混用会出现两套状态机打架。
4. **依赖膨胀**：langchain-core + langgraph 会让 `uv.lock` 显著增重，违背"保持轻量"。
5. **已有更轻的对标**：`TurnContext.parent_turn_id` 已是本项目自研的"父子节点"模式，对话层树只需复制同一模式到 message 层。

### LangGraph 唯一值得借鉴的点
**Checkpoint 的 `parent_config` 链式设计思想**——"每个状态快照记录上一个快照的 id，fork 时只需指定 fork 点"。这正是本 spec「消息节点化与父子关系」要求里 `parent_id` 字段的设计来源。**借鉴思想，不引入框架**。

### 决策摘要

| 选项 | 推荐度 | 理由 |
| --- | --- | --- |
| **A. 自研轻量树（本 spec 既有方案）** | ✅ 推荐 | ~200 行代码，无新依赖，契合"轻量 + 移除 LLM 组件"硬约束 |
| B. 引入 LangGraph | ❌ 不推荐 | 违背用户硬约束（移除 LLM 组件），依赖膨胀，与现有 turn 树/subagent 机制重叠 |
| C. 仅用 LangGraph Checkpoint（不引 StateGraph） | ⚠️ 不推荐 | 仍带 langchain-core 依赖，且只用 checkpoint 等于只用了"parent_id 链"——这点自研即可 |

---

## 补充：节点回退（Backtrack）能力

> 用户反馈：「如果是工作执行任务，把从某一节点回退也加入」。
> 适用场景：agent 执行多步工作类任务（写代码 / 调研 / 操作文件）走错方向时，用户需回退到走错前的节点重新指令，而非另开分支把错误路径一直留着。

### 与现有操作的区别

| 操作 | 语义 | 对后续节点 |
| --- | --- | --- |
| fork（分叉） | 从 N 长新分支，N 之后内容仍是某条活跃路径的一部分 | 保留、可见 |
| 切换分支 | 跳到另一条已存在分支的叶子 | 不变 |
| **rollback（回退）** | 退回 N，N 之后"不算了" | 软删除（`archived=true`），默认隐藏、可恢复 |

### 设计要点
- `MessageNode` 增加字段 `archived: bool = false`
- 回退走软删除而非物理删除：保留可恢复性，符合"不丢数据"原则
- 新 API `POST /api/chat/threads/{tid}/rollback` body `{to_message_id}`：
  - 校验 `to_message_id` 属于该 thread
  - 把 `to_message_id` 的所有后代（沿 `children_ids` 递归）置 `archived=true`
  - `active_leaf_id = to_message_id`
  - 前端默认只渲染 root→active_leaf 路径上 `archived=false` 的节点
- 回退后从 active leaf 发新消息：新节点 `archived=false`，自然成为新活跃路径；原被 archived 的后代保持隐藏
- 可恢复：提供"显示已归档节点"开关，archived 节点以置灰样式显示，可重新设为活跃

## ADDED Requirements（追加）

### Requirement: 节点回退（工作执行任务场景）
系统 SHALL 允许用户回退到 thread 内任意历史节点：该节点之后的所有后代标记为 `archived`（软删除），`active_leaf_id` 更新为该节点，UI 默认隐藏 archived 节点。

#### Scenario: 回退到历史节点
- **WHEN** 用户在节点 N 点击「回退到此」
- **THEN** N 的所有后代 `archived=true`，`active_leaf_id=N.id`，消息列表重新渲染为 root→N 路径且不含 archived 节点

#### Scenario: 回退后继续对话
- **WHEN** 用户在回退后的 active leaf N 发新消息
- **THEN** 新消息 `parent_id=N.id`、`archived=false`，成为新 `active_leaf`；原 archived 后代保持隐藏

#### Scenario: 恢复已归档节点
- **WHEN** 用户开启「显示已归档」或对归档节点点击「恢复」
- **THEN** archived 节点以置灰样式显示；恢复操作把该路径上 `archived` 翻回 `false` 并可重新设为 active leaf

#### Scenario: 回退不影响 LLM 上下文
- **WHEN** 回退后调用 `agent_history_path(active_leaf_id)`
- **THEN** 返回 root→active_leaf 路径，archived 后代不进入 LLM 上下文
