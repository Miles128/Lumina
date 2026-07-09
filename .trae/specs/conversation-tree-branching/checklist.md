# Checklist

## 方案决策（本阶段已满足）
- [x] spec.md 明确区分「turn 内部子 agent 树」与「对话轮次消息树」两套树
- [x] spec.md 含 LangGraph 可行性评估章节并给出「不引入」结论
- [x] LangGraph 决策与用户硬约束（移除 LLM 组件、保持轻量）一致
- [x] 推荐方案（自研轻量树）给出数据模型、API、前端、迁移、测试覆盖
- [x] tasks.md 按 Phase 1-4 拆分（含节点回退），依赖关系清晰
- [x] spec.md 含「节点回退（Backtrack）」Requirement 与 Scenario

## 实施验收（待执行，当前阶段不实施）
- [x] 消息节点化：每条消息有稳定 `id` + `parent_id`
- [x] thread 记录 `active_leaf_id` 驱动渲染与 LLM history
- [x] fork API：`POST /api/chat` 接受 `parent_message_id`
- [x] 兄弟分支切换：`<` `>` 导航调用 `set_active_leaf`
- [x] 对话地图视图：渲染整树，点击节点跳转/设为 active leaf
- [x] 旧数据迁移：扁平 `messages` 自动补 `id`/`parent_id`/`active_leaf_id`，前端 localStorage 同步迁移
- [x] 节点回退：`rollback` API + `archived` 软删除 + `active_leaf` 更新
- [x] 回退后 `active_path` / LLM 上下文不含 archived 节点
- [x] 回退后新消息续接正确，原后代保持隐藏
- [x] archived 节点可恢复显示与重新激活
- [x] turn 内部子 agent 树机制未被改动（`TurnContext` / `SessionStore` / `pause_*` 原样）
- [x] 未引入 `langgraph` / `langchain-core` 依赖（pyproject.toml 校验）
- [x] `uv run pytest` 全绿
- [x] `uv run ruff check src tests` 无新增错误
- [x] `uv run mypy src` 无新增错误
