# F21 反思记忆（Reflexion-style）设计文档

**日期：** 2026-07-14
**状态：** 设计已确认，待实现
**关联 PRD：** F21（`docs/PRD.md:357`，状态将从 Research 升级为 Done(MVP)）

---

## 1. 概述

为 Lumina 增加反思记忆能力：Build profile 下的失败 turn 由 harness 启发式判定命中失败信号后，自动 spawn 一个只读的 reflect 子 agent 用 LLM 生成结构化反思，写入扩展后的 episodes 表；下一个 turn 开始时按当前 user_message 检索 top-3 相关历史失败反思，注入 system prompt 的「## 历史教训」段，供 LLM 避免重蹈覆辙。

### 核心原则

- **失败才反思**：成功 turn 不调 reflector，零额外 LLM 成本
- **仅 Build 触发，任意 profile 注入**：写入限制在 Build（失败信号清晰），读取开放给所有 profile（教训跨模式可见）
- **反思失败不阻塞主流程**：reflector 超时/异常只记日志，不影响已返回的回复
- **同步触发**：在 `_finalize_agent_result` 内 spawn（与 verify sub-agent 同步等待返回），保证反思在当前 turn 末尾完成、下一个 turn 可检索到
- **轻量复用**：不引入 LangGraph / Prefect，复用现有 SubAgentRunner / episodes 表 / NotesTool 范式

### 非目标（v1 不做）

- 反思管理 UI（用户可删 DB 重建）
- `reflect` 工具开放给 LLM 主动调用
- `failure_mode_guard` 动态升级（保持静态 5 条）
- 主动 TTL 清理 / 去重
- 正向反思（成功模式）
- F22 代码级自修复（独立 FR）

---

## 2. 架构总览

### 数据流

```
Turn 完成（Build profile）
  ↓
_finalize_agent_result 收尾
  ↓
ReflectionTrigger 启发式判定
  ├─ 未命中失败信号 → 不反思，正常返回
  └─ 命中失败信号 ↓
      ↓
spawn_subagent(archetype="reflect", goal=..., context={失败信号+turn 摘要})
  ↓
ReflectSubAgentRunner（复用 SubAgentRunner）
  ├─ 只读工具集：file_read / search_files / search_memory / session_search / shibei_search
  ├─ REFLECT_PROMPT 要求输出结构化 JSON
  └─ max_steps=4（比 verify 的 6 步更短）
  ↓
解析 reflector 输出 JSON
  ↓
episodes.save_episode(success=False, failure_mode=..., reflection_text=..., thread_id=...)
  ↓
落库 ~/.lumina/memories/episodes.db

下一 turn 开始（任意 profile）
  ↓
_build_system_prompt 末尾追加「## 历史教训」段
  ↓
search_episodes(success_only=False, query=user_message, limit=3)
  ↓
拼 top-3 反思摘要进 prompt（每条 ≤200 字符）
```

### 模块清单

| 模块 | 职责 | 位置 |
|------|------|------|
| `ReflectionTrigger` | 启发式判定 turn 是否失败 | `src/secretary/agent/reflection/trigger.py`（新文件） |
| `ReflectArchetype` | reflect 子 agent 的 prompt + 工具集 + 步数 | `src/secretary/agent/subagent/registry.py`（扩展） |
| 反思执行 + 输出解析 | 复用 `SubAgentRunner`，无需新 runner | `src/secretary/agent/subagent/runner.py` |
| `episodes` 表扩展 | 加 `failure_mode` / `reflection_text` / `thread_id` 字段 + FTS5 扩展 | `src/secretary/services/lumina_memory.py` |
| 注入逻辑 | top-K 检索 + 拼接 system prompt | `src/secretary/agent/chat_service.py`（扩展 `_build_system_prompt`） |
| 触发整合 | `_finalize_agent_result` 末尾触发 | `src/secretary/agent/chat_service.py` |

### 关键约束

- 仅 Build profile 触发反思写入（任意 profile 注入）
- 失败才反思：成功 turn 不调 reflector
- 反思失败不阻塞主流程：reflector 超时/异常只记日志
- 同步触发：在 `_finalize_agent_result` 内 spawn
- reflector 受 MAX_SPAWN_DEPTH=1 约束，不可链式调用

---

## 3. 失败检测启发式规则（ReflectionTrigger）

### 5 类失败信号

`ReflectionTrigger.evaluate(turn_context) -> FailureSignal | None`，按优先级短路判定。

| # | 信号 | 判定条件 | failure_mode 分类 | 来源 |
|---|------|----------|-------------------|------|
| **F1** | 用户显式纠正 | 当前 user_message 含纠正语义关键词且**上一 turn 为 Build** | `user_correction` | 启发式关键词匹配 |
| **F2** | Verify sub-agent 返回 Fail | 本 turn 内有 spawn_subagent(verify) 的 summary 含 `Pass: False` 或 `Fail` | `verify_failed` | 扫描本 turn tool 调用历史 |
| **F3** | Grounding 未通过 | `LoopResult.grounding_verified == False` | `grounding_failed` | LoopResult 字段 |
| **F4** | Max steps 耗尽 | `LoopResult.total_steps >= max_steps` | `max_steps_exhausted` | LoopResult 字段 |
| **F5** | Turn 异常/取消 | turn 以 `failed` / `cancelled` 状态结束 | `turn_aborted` | TurnContext.status |

### 优先级与短路

- 按优先级 F4 → F2 → F1 → F3 → F5 短路判定（F4 优先：max_steps 耗尽是更根本的失败）
- 命中第一个即返回，不组合多信号
- 全部未命中返回 None（不反思）

### 启发式实现要点

**F1 用户纠正**（最值得反思的信号）：
- 关键词集合：`{"不对","错了","重新","撤销","不要这样","revert","rollback","不要这样改","这不是我要的"}`
- 必须配合"上一 turn 为 Build"才触发——Ask 模式的"错了"不反思
- 关键词命中即触发，不做语义判定（避免额外 LLM）

**F2 verify Fail**：
- 扫描本 turn 的 `tool_call_history`，找 archetype=verify 的 spawn_subagent
- 检查返回 summary 文本是否含 `"Pass: False"` / `"Fail"` / `"Issues found"`
- 同时把 verify 的 `Suggested fixes` 一并传给 reflector 作为输入

**F3/F4/F5**：直接读 LoopResult / TurnContext 字段，零成本。

### FailureSignal 数据结构

```python
@dataclass
class FailureSignal:
    mode: str  # user_correction | verify_failed | grounding_failed | max_steps_exhausted | turn_aborted
    summary: str  # 一句话失败描述
    user_message: str  # 当前 user_message（纠正场景）或上一 turn 的 user_message
    raw_reply: str  # LLM 原始输出（截断到 2000 字符）
    tool_calls_summary: list[str]  # 本 turn 工具调用摘要（name + 简短 result）
    verify_issues: str | None  # 若 F2，附带 verify 的 issues/suggested fixes
```

### 不做的检测

- 不检测"过度修改/失控重构"（需要 diff 分析，v1 太重，failure_mode_guard 静态提示继续负责）
- 不检测"乐观路径"（需要语义判定，避免额外 LLM）
- 不组合多信号（短路返回第一个命中）

### 触发频率预期

- 日常使用中失败 turn 占比 < 20%
- 每个失败 turn 多一次 4 步 reflector 调用（~2-4 秒延迟）
- 成功 turn 零开销

---

## 4. episodes 表扩展 + reflect sub-agent 设计

### 4.1 episodes 表扩展

**当前 schema**（`src/secretary/services/lumina_memory.py:219-227`）：

```sql
CREATE TABLE episodes (
    episode_id TEXT PRIMARY KEY,
    task TEXT,
    steps_json TEXT,
    result TEXT,
    success INTEGER,
    tools_used TEXT,
    created_at TEXT
)
```

**扩展后**：

```sql
CREATE TABLE episodes (
    episode_id TEXT PRIMARY KEY,
    task TEXT,
    steps_json TEXT,
    result TEXT,
    success INTEGER,
    tools_used TEXT,
    created_at TEXT,
    -- F21 新增字段
    failure_mode TEXT,           -- user_correction | verify_failed | grounding_failed | max_steps_exhausted | turn_aborted
    reflection_text TEXT,        -- reflector 生成的结构化反思（JSON 字符串）
    thread_id TEXT               -- 关联对话线程，便于追溯
)
```

**FTS5 扩展**：现有 `episodes_fts` 表支持 task + result + steps_json 检索。新增字段：
- `failure_mode` 加进 FTS5 列（可按失败类型过滤）
- `reflection_text` 加进 FTS5 列（反思内容可被关键词检索到）

**Migration**：用现有 `_migrate` 模式（lumina_memory.py 已有 SQLite ALTER TABLE 兼容写法），新字段允许 NULL，老数据无影响。

**`save_episode` 签名扩展**：

```python
def save_episode(
    self,
    task: str,
    steps: list[str],
    result: str,
    success: bool,                      # 现在真正使用，不再恒传 True
    tools_used: list[str] | None = None,
    *,
    failure_mode: str | None = None,
    reflection_text: str | None = None,
    thread_id: str | None = None,
) -> str: ...
```

**`search_episodes` 签名扩展**：

```python
def search_episodes(
    self,
    query: str,
    limit: int = 5,
    *,
    success_only: bool | None = None,  # None=全部, True=只成功, False=只失败
) -> list[Episode]: ...
```

**修复现有 bug**：当前 `chat_service.py:1211` 恒传 `success=True`——改为根据 `LoopResult` 推断：
```python
success = result.grounding_verified and not result.cancelled and result.total_steps < result.max_steps
```

### 4.2 reflect archetype 注册

在 `src/secretary/agent/subagent/registry.py` 新增 reflect archetype，与 verify 对称。

**REFLECT_PROMPT**（要求结构化 JSON 输出）：

```
You are a reflection agent. Your job: analyze a failed turn and produce a structured lesson for future turns.

You have read-only tools. Use them ONLY if needed to confirm a specific fact (e.g., read a file that was patched wrong). Do not explore broadly — max 4 steps.

Input context will include:
- failure_mode: why this turn was flagged as failed
- user_message: what the user wanted
- raw_reply: what the LLM produced
- tool_calls_summary: tools invoked and their outcomes
- verify_issues: (if applicable) issues found by verify sub-agent

Output STRICT JSON, nothing else:
{
  "failure_summary": "一句话总结失败本质（≤120 字符）",
  "root_cause": "根本原因（≤300 字符）",
  "lesson": "可迁移的教训，未来类似场景应如何避免（≤300 字符）",
  "related_files": ["相关文件路径（如有）"],
  "failure_tags": ["1-3 个标签，如 patch_error, shell_failure, scope_creep, wrong_abstraction"]
}

Rules:
- Be specific, not generic. "应更仔细" is useless; "patch 前应先用 search_files 确认函数签名" is useful.
- Focus on actionable lessons, not blame.
- If the failure is genuinely uninformative (e.g., user just changed mind), output {"failure_summary": "non-informative", ...empty fields} and we'll skip saving.
```

**工具集**（只读，与 verify 一致 + 记忆）：

```python
REFLECT_TOOLS = [
    "list_dir", "file_read", "search_files", "search_memory",
    "session_search", "shibei_search",
]
```

**参数配置**（registry.py 注册）：

| 项 | 值 | 理由 |
|----|-----|------|
| `archetype` | `"reflect"` | 新增 |
| `max_steps` | `4` | 比 verify 的 6 步短——反思不应长跑，多数情况 1-2 步够 |
| `timeout` | `60s` | 比 SUBAGENT_TIMEOUT_SEC=120 短，失败不阻塞主流程太久 |
| `success_criteria` | 不要求 | reflect 不验证外部条件，只产出反思 |
| `tools` | 上述只读集 | 允许读文件确认，禁止写 |

### 4.3 reflect 调用流程

在 `_finalize_agent_result`（`src/secretary/agent/chat_service.py:1165`）末尾，reply 已生成后：

```python
# 1. 启发式判定
signal = self._reflection_trigger.evaluate(
    profile=effective_profile,
    user_message=user_message,
    raw_reply=raw_reply,
    loop_result=result,
    turn_status=turn_ctx.status,
    tool_call_history=result.tool_calls,
)

# 2. 仅 Build profile + 命中信号才反思
if signal is not None and effective_profile == "build":
    try:
        reflection_json = self._spawn_reflect_subagent(signal)
        # 3. 写入扩展的 episodes 表
        self._lumina.save_episode(
            task=user_message[:500],
            steps=[],
            result=raw_reply[:2000],
            success=False,
            failure_mode=signal.mode,
            reflection_text=reflection_json,
            thread_id=thread_id,
        )
    except Exception as e:
        logger.warning("reflection failed: %s", e)  # 不阻塞主流程
```

**`_spawn_reflect_subagent`** 直接复用 `SubAgentRunner.run()`，传入：
- `archetype="reflect"`
- `goal=f"分析失败 turn: mode={signal.mode}, summary={signal.summary}"`
- `context=json.dumps(signal.__dict__)`

### 4.4 reflect sub-agent 约束

- **不做 reflector 失败重试**：reflector 超时/异常只记日志，不重试（避免雪崩）
- **不做 reflector 链式调用**：reflector 不能再 spawn 子 agent（受 MAX_SPAWN_DEPTH=1 约束）
- **不做反思去重**：同一 failure_mode 的反思可能重复，但 FTS5 检索时靠相关性排序自然去重
- **不存 raw_reply 全文**：截断到 2000 字符，避免 DB 膨胀
- **不暴露 reflect 为 LLM 可调用工具**：reflect 只由 harness 在失败时自动触发，不开放给 LLM 主动调

---

## 5. top-K 注入设计

### 5.1 注入位置

在 `_build_system_prompt`（`src/secretary/agent/chat_service.py:1386`）末尾追加「## 历史教训」段，紧跟现有「## 持久笔记」段之后：

```
... 现有 system prompt 内容 ...

## 持久笔记（跨会话保留，可用 notes 工具更新）
<NOTES.md 内容>

## 历史教训（按相关性检索，避免重蹈覆辙）
<top-3 反思摘要>

## 对话规则
...
```

**位置选择理由**：
- 放在「持久笔记」之后、「对话规则」之前——属于"上下文背景"而非"行为约束"
- 不与 `failure_mode_guard`（loop.py:1646，在 instruction 末尾）合并——后者是行为约束，职责分离

### 5.2 检索逻辑

```python
def _build_reflections_block(self, user_message: str) -> str:
    """检索 top-3 相关历史失败反思，拼成 system prompt 段。"""
    if not self._lumina or not user_message.strip():
        return ""

    # 复用 search_episodes，加 success_only=False 过滤
    episodes = self._lumina.search_episodes(
        query=user_message,
        limit=3,
        success_only=False,  # False = 只返回失败
    )
    if not episodes:
        return ""

    lines = ["## 历史教训（按相关性检索，避免重蹈覆辙）"]
    for ep in episodes:
        try:
            refl = json.loads(ep.reflection_text) if ep.reflection_text else {}
            summary = refl.get("failure_summary", "")
            lesson = refl.get("lesson", "")
            if not summary or summary == "non-informative":
                continue
            # 每条 ≤200 字符，控制 prompt 体积
            entry = f"- [{ep.failure_mode}] {summary} → {lesson[:120]}"
            lines.append(entry[:200])
        except (json.JSONDecodeError, AttributeError):
            continue

    if len(lines) == 1:  # 只有标题，无有效条目
        return ""
    return "\n".join(lines) + "\n\n"
```

**关键设计**：
- **检索查询 = 当前 user_message**：让反思与当前任务语义相关，而非全量注入
- **`success_only=False` 参数**：扩展 `search_episodes` 签名，区分成功/失败检索
- **每条 ≤200 字符**：top-3 共 ≤600 字符，远低于 MEMORY.md 的 2200 字符上限，不会撑爆 prompt
- **跳过 `non-informative` 条目**：reflector 判定无信息价值的反思不注入

### 5.3 任意 profile 注入

**重要**：注入逻辑不限制 profile。

- 写入反思：仅 Build（失败才有反思价值）
- 读取反思：Ask / Plan / Build 均注入

**理由**：
- 用户在 Build 模式踩过的坑，在 Ask/Plan 模式提问时也应能看到
- 注入成本极低（3 条 ≤600 字符），无理由限制
- 符合"反思记忆作为长期记忆"的定位

### 5.4 缓存影响

**`_instruction_cache` 不受影响**：
- 反思注入在 `_build_system_prompt`（system 消息），不在 `_instruction_text`（instruction 尾部）
- `_instruction_cache[native]` 只缓存 instruction 文本，与 system prompt 分离
- 每次 turn 开始时 `_build_system_prompt` 重新构建，会拉取最新反思——无需破坏缓存设计

**`failure_mode_guard` 保持静态**（v1 不升级）：
- v1 用「## 历史教训」段独立承担"可学习失败库"职责
- failure_mode_guard 继续负责"行为提醒"，两者职责分离
- v2 可考虑动态升级（待 v1 验证注入效果后再定）

### 5.5 容量与清理

**反思记录增长控制**：
- 不做主动 TTL 清理（与 episodes 表一致，靠 `prune_stale` 的 72h/200 条上限兜底）
- 不做反思去重（FTS5 相关性排序自然降权重复条目）
- **未来扩展点**：若反思积累 > 100 条导致检索质量下降，v2 加"按 failure_mode 分组保留 top-N"的清理策略

---

## 6. 测试策略

| 层级 | 测试内容 | 位置 |
|------|----------|------|
| **单元** | `ReflectionTrigger.evaluate` 5 类信号判定 + 优先级短路 | `tests/agent/test_reflection_trigger.py` |
| **单元** | `save_episode` 扩展字段写入 + migration 兼容老数据 | `tests/services/test_lumina_memory.py` |
| **单元** | `search_episodes(success_only=False)` 过滤逻辑 | `tests/services/test_lumina_memory.py` |
| **单元** | `_build_reflections_block` 拼接 + 截断 + 跳过 non-informative | `tests/agent/test_chat_service.py` |
| **集成** | reflect archetype 注册 + SubAgentRunner 调用（mock LLM） | `tests/agent/subagent/test_runner.py` |
| **集成** | `_finalize_agent_result` 触发反思 + 写库（mock subagent） | `tests/agent/test_chat_service.py` |
| **E2E** | Build 失败 turn → 反思写入 → 下一 turn 注入 | `tests/e2e/test_reflection_flow.py` |

**验证命令**（遵循 AGENTS.md）：

```bash
uv run pytest tests/agent/test_reflection_trigger.py tests/services/test_lumina_memory.py -v
uv run ruff check src tests
uv run mypy src
```

---

## 7. 实现范围与 PRD 更新

### v1 做

- episodes 表加 3 字段（`failure_mode` / `reflection_text` / `thread_id`）+ FTS5 扩展
- 修复 `save_episode` 恒传 `success=True` 的 bug
- 新增 `ReflectionTrigger`（5 类信号，优先级短路）
- 新增 reflect archetype（4 步、只读、结构化 JSON 输出）
- `_finalize_agent_result` 末尾触发反思（仅 Build）
- `_build_system_prompt` 注入 top-3 反思（任意 profile）
- 单元 + 集成 + 1 个 E2E 测试

### v1 不做

- 反思管理 UI
- reflect 工具开放给 LLM 主动调用
- `failure_mode_guard` 动态升级
- 主动 TTL 清理 / 去重
- 正向反思（成功模式）
- F22 代码级自修复

### PRD 更新

- `F21` 状态从 `Research` 改为 `Done（MVP）`
- 在 §12 实现索引加路径：`src/secretary/agent/reflection/`

---

## 8. 实现索引（锚点）

| 区域 | 路径 | 改动类型 |
|------|------|----------|
| 失败检测 | `src/secretary/agent/reflection/trigger.py` | 新文件 |
| reflect archetype 注册 | `src/secretary/agent/subagent/registry.py` | 扩展 |
| reflector 工具集策略 | `src/secretary/agent/subagent/policy.py` | 扩展 |
| episodes 表 + FTS5 | `src/secretary/services/lumina_memory.py` | 扩展 |
| 触发整合 + 注入 | `src/secretary/agent/chat_service.py` | 扩展 |
| `_finalize_agent_result` | `src/secretary/agent/chat_service.py:1165` | 触发点 |
| `_build_system_prompt` | `src/secretary/agent/chat_service.py:1386` | 注入点 |
| `failure_mode_guard`（保持静态） | `src/secretary/agent/loop.py:1646-1656` | 不改 |

---

*End of design document · 设计文档结束*
