# Tasks

## Phase 1 — 后端：消息节点化与 active path

- [x] Task 1: 消息节点 schema 与迁移（chat_threads.py）
  - [x] 1.1 为 `ChatThread.messages` 每条补 `id`（`m_<uuid8>`）、`parent_id`（默认 `""`）；`load_document` 读取时若发现无 `id` 的旧消息，按顺序生成 id 并链式补 `parent_id`，`active_leaf_id` 缺省取末条 id
  - [x] 1.2 `save_document` 写回时保留 `active_leaf_id`；`create_thread` 初始化 `active_leaf_id=""`
  - [x] 1.3 单测：旧扁平 messages 加载后 id/parent_id/active_leaf 正确；新 thread 默认值正确
- [x] Task 2: append_turn 支持分支与 active path 回溯（chat_threads.py）
  - [x] 2.1 `append_turn(thread_id, user_message, assistant_message, parent_message_id="")`：`parent_message_id` 为空时取当前 `active_leaf_id`；为新 user/assistant 消息生成 id、设 `parent_id`；更新 `active_leaf_id` 为新 assistant 消息 id
  - [x] 2.2 `active_path(thread_id)`：从 `active_leaf_id` 沿 `parent_id` 回溯到 root，反转返回有序消息列表
  - [x] 2.3 `agent_history(thread_id)` 改为基于 `active_path`，再按 `MAX_HISTORY_MESSAGES` 截断（取路径末段，保持 role/content 规范化）
  - [x] 2.4 `set_active_leaf(thread_id, leaf_id)`：校验 leaf 属于该 thread 后更新
  - [x] 2.5 单测：fork 后 active_path 正确；切换 active_leaf 后 history 变化；截断行为
- [x] Task 3: ChatService 透传 parent_message_id（chat_service.py）
  - [x] 3.1 `reply()` 增加 `parent_message_id: str | None`，传入 `_append_history`/`append_turn`
  - [x] 3.2 `_append_history` 在 thread 模式下调用 `append_turn(..., parent_message_id=...)`
  - [x] 3.3 单测：带 parent_message_id 的 reply 写入正确父子关系
- [x] Task 4: API 接口扩展（app.py）
  - [x] 4.1 `ChatRequest` 增 `parent_message_id: str = ""`；`/api/chat` 与 `/api/chat/confirm` 透传
  - [x] 4.2 新增 `PUT /api/chat/threads/{thread_id}/active-leaf`（body: `leaf_id`）→ `set_active_leaf`
  - [x] 4.3 新增 `GET /api/chat/threads/{thread_id}/tree`→ 返回 `{nodes:[{id,parent_id,role,preview,active}], root_id, active_leaf_id}`
  - [x] 4.4 接口测试

## Phase 2 — 前端：分支交互

- [x] Task 5: 消息 ID 与发送带 parent（chat.js）
  - [x] 5.1 `persistMessage` 写入时带 `id`/`parent_id`（沿用后端返回或前端生成 `m_<uuid8>`）
  - [x] 5.2 发送请求体加 `parent_message_id`（默认空=续接 active leaf；fork 时为指定消息 id）
  - [x] 5.3 `renderCurrentThreadMessages` 改为按 active path 渲染（从后端 tree 或本地计算路径）
  - [x] 5.4 localStorage 读取时复用后端迁移逻辑（补 id/parent_id/active_leaf）
- [x] Task 6: fork 入口与兄弟导航 UI（chat.js / chat.css）
  - [x] 6.1 每条消息 hover 显示「从此新开分支」按钮（user 与 assistant 均可）
  - [x] 6.2 点击 fork：进入「待发」状态，输入框聚焦，记录 `pendingParentId`；发送时携带
  - [x] 6.3 消息有多个子分支时显示 `< N/M >` 切换器；切换调用 active-leaf 接口并重渲染
  - [x] 6.4 样式：分支指示器、当前 active path 高亮、fork 态输入框提示
- [x] Task 7: Playwright 冒烟（tests/e2e）
  - [x] 7.1 发送消息→fork 历史消息→切换兄弟→断言 DOM 与 active 高亮正确

## Phase 3 — 前端：对话地图视图

- [x] Task 8: 对话地图模块（desktop/ui/conversation_map.js + css）
  - [x] 8.1 新增 `conversation_map.js`：拉取 `/tree`，用层级树布局（左→右）在 canvas/SVG 渲染节点+边；user/assistant 区分样式；active path 高亮

## Phase 4 — 节点回退（Backtrack，工作执行任务场景）

- [x] Task 9: 回退数据模型与后端（chat_threads.py + app.py）
  - [x] 9.1 `MessageNode` 增 `archived: bool = false`；`load_document` 兼容旧数据（缺字段补 false）
  - [x] 9.2 `rollback_to(thread_id, to_message_id)`：校验归属 → 递归沿 `children_ids` 把后代 `archived=true` → `active_leaf_id=to_message_id` → 持久化
  - [x] 9.3 `active_path` / `agent_history_path` 过滤 `archived=true` 节点
  - [x] 9.4 新增 `POST /api/chat/threads/{tid}/rollback` body `{to_message_id}`；`restore_archived(thread_id, message_id)` 可选恢复接口
  - [x] 9.5 单测：回退后后代 archived 正确、active_path 不含 archived、回退后新消息续接正确、恢复翻回 false
- [x] Task 10: 回退前端 UI（chat.js + chat.css）
  - [x] 10.1 每条消息 hover 显示「回退到此」按钮（工作执行类 thread 才高亮提示，普通闲聊可选）
  - [x] 10.2 点击回退 → 调 rollback API → 重渲染（archived 节点不显示）
  - [x] 10.3 「显示已归档」开关：开启后 archived 节点置灰显示，提供「恢复」入口
  - [x] 10.4 Playwright 冒烟：回退→续接→显示已归档→恢复，断言 DOM 与 active 状态
