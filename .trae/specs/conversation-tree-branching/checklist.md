# Checklist

## 方案决策（本阶段已满足）
- [x] spec.md 明确区分「turn 内部子 agent 树」与「对话轮次消息树」两套树
- [x] spec.md 含 LangGraph 可行性评估章节并给出「不引入」结论
- [x] LangGraph 决策与用户硬约束（移除 LLM 组件、保持轻量）一致
- [x] 推荐方案（自研轻量树）给出数据模型、API、前端、迁移、测试覆盖
- [x] tasks.md 按 Phase 1-3 拆分，依赖关系清晰

## 实施验收（待执行，当前阶段不实施）
- [ ] 消息节点化：每条消息有稳定 `id` + `parent_id`
- [ ] thread 记录 `active_leaf_id` 驱动渲染与 LLM history
- [ ] fork API：`POST /api/chat` 接受 `parent_message_id`
- [ ] 兄弟分支切换：`<` `>` 导航调用 `set_active_leaf`
- [ ] 对话地图视图：渲染整树，点击节点跳转/设为 active leaf
- [ ] 旧数据迁移：扁平 `messages` 自动补 `id`/`parent_id`/`active_leaf_id`，前端 localStorage 同步迁移
- [ ] turn 内部子 agent 树机制未被改动（`TurnContext` / `SessionStore` / `pause_*` 原样）
- [ ] 未引入 `langgraph` / `langchain-core` 依赖（pyproject.toml 校验）
- [ ] `uv run pytest` 全绿
- [ ] `uv run ruff check src tests` 无新增错误
- [ ] `uv run mypy src` 无新增错误
