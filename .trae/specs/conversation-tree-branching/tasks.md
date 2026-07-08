# Tasks

## Phase 1 — 后端：消息节点化与 active path

- [ ] Task 1: 消息节点 schema 与迁移（chat_threads.py）
  - [ ] 1.1 为 `ChatThread.messages` 每条补 `id`（`m_<uuid8>`）、`parent_id`（默认 `""`）；`load_document` 读取时若发现无 `id` 的旧消息，按顺序生成 id 并链式补 `parent_id`，`active_leaf_id` 缺省取末条 id
  - [ ] 1.2 `save_document` 写回时保留 `active_leaf_id`；`create_thread` 初始化 `active_leaf_id=""`
  - [ ] 1.3 单测：旧扁平 messages 加载后 id/parent_id/active_leaf 正确；新 thread 默认值正确
- [ ] Task 2: append_turn 支持分支与 active path 回溯（chat_threads.py）
  - [ ] 2.1 `append_turn(thread_id, user_message, assistant_message, parent_message_id="")`：`parent_message_id` 为空时取当前 `active_leaf_id`；为新 user/assistant 消息生成 id、设 `parent_id`；更新 `active_leaf_id` 为新 assistant 消息 id
  - [ ] 2.2 `active_path(thread_id)`：从 `active_leaf_id` 沿 `parent_id` 回溯到 root，反转返回有序消息列表
  - [ ] 2.3 `agent_history(thread_id)` 改为基于 `active_path`，再按 `MAX_HISTORY_MESSAGES` 截断（取路径末段，保持 role/content 规范化）
  - [ ] 2.4 `set_active_leaf(thread_id, leaf_id)`：校验 leaf 属于该 thread 后更新
  - [ ] 2.5 单测：fork 后 active_path 正确；切换 active_leaf 后 history 变化；截断行为
- [ ] Task 3: ChatService 透传 parent_message_id（chat_service.py）
  - [ ] 3.1 `reply()` 增加 `parent_message_id: str | None`，传入 `_append_history`/`append_turn`
  - [ ] 3.2 `_append_history` 在 thread 模式下调用 `append_turn(..., parent_message_id=...)`
  - [ ] 3.3 单测：带 parent_message_id 的 reply 写入正确父子关系
- [ ] Task 4: API 接口扩展（app.py）
  - [ ] 4.1 `ChatRequest` 增 `parent_message_id: str = ""`；`/api/chat` 与 `/api/chat/confirm` 透传
  - [ ] 4.2 新增 `PUT /api/chat/threads/{thread_id}/active-leaf`（body: `leaf_id`）→ `set_active_leaf`
  - [ ] 4.3 新增 `GET /api/chat/threads/{thread_id}/tree`→ 返回 `{nodes:[{id,parent_id,role,preview,active}], root_id, active_leaf_id}`
  - [ ] 4.4 接口测试

## Phase 2 — 前端：分支交互

- [ ] Task 5: 消息 ID 与发送带 parent（chat.js）
  - [ ] 5.1 `persistMessage` 写入时带 `id`/`parent_id`（沿用后端返回或前端生成 `m_<uuid8>`）
  - [ ] 5.2 发送请求体加 `parent_message_id`（默认空=续接 active leaf；fork 时为指定消息 id）
  - [ ] 5.3 `renderCurrentThreadMessages` 改为按 active path 渲染（从后端 tree 或本地计算路径）
  - [ ] 5.4 localStorage 读取时复用后端迁移逻辑（补 id/parent_id/active_leaf）
- [ ] Task 6: fork 入口与兄弟导航 UI（chat.js / chat.css）
  - [ ] 6.1 每条消息 hover 显示「从此新开分支」按钮（user 与 assistant 均可）
  - [ ] 6.2 点击 fork：进入「待发」状态，输入框聚焦，记录 `pendingParentId`；发送时携带
  - [ ] 6.3 消息有多个子分支时显示 `< N/M >` 切换器；切换调用 active-leaf 接口并重渲染
  - [ ] 6.4 样式：分支指示器、当前 active path 高亮、fork 态输入框提示
- [ ] Task 7: Playwright 冒烟（tests/e2e）
  - [ ] 7.1 发送消息→fork 历史消息→切换兄弟→断言 DOM 与 active 高亮正确

## Phase 3 — 前端：对话地图视图

- [ ] Task 8: 对话地图模块（desktop/ui/conversation_map.js + css）
  - [ ] 8.1 新增 `conversation_map.js`：拉取 `/tree`，用层级树布局（左→右）在 canvas/SVG 渲染节点+边；user/assistant 区分样式；active path 高亮
