# Design: Unify user facts into MEMORY.md + SOUL identity

**Date:** 2026-08-01  
**Status:** Implemented  
**Decision:** Approach B / implementation path 2（合并重定向）  
**Defaults:** 后台思考、记忆摘要 **默认开启**

## Problem

1. 设置「持久记忆」页只**展示**后台思考 / 记忆摘要为「已关闭」，无开关；二者默认来自环境变量且为 `false`。
2. MEMORY.md 内容可能被测试污染（如 `Test env fact`），用户感知「显示不准」；个人事实与 MEMORY.md 双通道（个人画像）增加认知负担。
3. 个人画像有编辑页，但「对话推断」只读、难用；用户要求去掉画像，合并进 MEMORY.md。
4. 灵犀身份应等于可编辑的 `SOUL.md`；当前「你是谁」仍走硬编码 `identity.py`，与 SOUL 双轨。

## Goals

- 用户事实唯一落点：`~/.lumina/memories/MEMORY.md`
- 灵犀身份唯一人设：`~/.lumina/SOUL.md`（设置页可编辑保存）
- 设置页可开关后台思考 / 记忆摘要，并持久化；**默认开**
- 去掉设置中的「个人画像」；系统提示不再单独注入 Profile 段

## Non-goals

- 不物理删除全部 ProfileService / LocalDocumentsProfiler 代码库（本迭代做重定向与停用表面 API；深度删文件可后续）
- 不改拾贝（Shibei）集成契约
- 不扩大 MEMORY.md 为无限长日志（保留上限，可略放宽）

## Architecture

```
设置页
  ├─ 身份 SOUL     → GET/PUT /api/agent/soul  → ~/.lumina/SOUL.md
  └─ 持久记忆
        ├─ MEMORY.md 编辑器 → GET/PUT /api/memory/durable
        └─ 后台任务开关     → agent.json.background.*

对话系统提示
  ├─ SOUL.md（身份与风格）
  ├─ MEMORY.md（用户 + 环境/项目事实）
  └─ 可选：检索命中（会话/本地文档/拾贝）——不再注入「用户画像」专段

后台
  ├─ ScheduledThink     → 只 mutate MEMORY.md（允许用户事实）
  └─ MemorySummarizer   → 写入 MEMORY.md 会话摘要段
```

## Data model

### MEMORY.md

- Path: `{data_dir}/memories/MEMORY.md`
- Char cap: keep `MEMORY_MD_MAX_CHARS`（建议 2200 → **4000**，容纳原画像合并）
- Content: 用户事实 + 环境/项目事实 + 每日会话摘要（由 summarizer upsert）
- Migration (once on startup or first durable GET):
  1. If `{data_dir}/user_profile.md` non-empty and not yet migrated:
  2. Append under heading `## Migrated from user profile` into MEMORY.md（截断到上限）
  3. Write marker `{data_dir}/memories/.profile_migrated` or rename `user_profile.md` → `user_profile.md.retired`

### Background settings（新）

Persist under `~/.lumina/agent.json`:

```json
{
  "background": {
    "think_enabled": true,
    "think_interval_hours": 6,
    "memory_summary_enabled": true,
    "memory_summary_hour": 23
  }
}
```

- **Defaults: all enabled as above**
- Env vars `SECRETARY_THINK_*` / `SECRETARY_MEMORY_SUMMARY_*` remain as **override fallback** when agent.json 未写 background 块时；一旦用户在 UI 保存，以 agent.json 为准
- `GET /api/background`（或扩展现有 background status endpoint）返回 effective flags + last run
- `PUT /api/background` 更新 agent.json.background

### SOUL.md

- Path / API unchanged: `GET/PUT /api/agent/soul`
- Settings nav label: 「人格 SOUL」→「身份 SOUL」
- Default template: remove「用户画像」措辞，改为「MEMORY.md / 本地记忆描述用户；SOUL 只描述灵犀」
- Identity replies: `get_identity_reply()` reads `load_soul(data_dir)`；若用户 SOUL 过短/空则用 `DEFAULT_SOUL` 渲染简短自我介绍（可从 Identity 段拼一段自然语言，或附短固定产品句）
- `identity.py` 保留：问句分类、作者回复（可选仍短固定）；删除或停用长篇 `LUMINA_IDENTITY_INTRO` 作为主文案源

## API / UI changes

| Surface | Change |
|---------|--------|
| Settings → 个人画像 | Remove nav + pane |
| Settings → 持久记忆 | Editor + save；toggle 后台思考 / 记忆摘要；去掉「请编辑个人画像」文案 |
| Settings → 身份 SOUL | Rename；keep editor/save |
| `/api/profile*` | Remove or return 410 Gone |
| Chat system prompt | Drop profile markdown block；inject SOUL + MEMORY only |
| Chat auto-write profile | Retarget to MEMORY.md append/mutate（或仅依赖 memory tool + scheduled think） |
| ScheduledThink prompt | Delete「用户信息勿写 MEMORY」规则；改为可写用户稳定事实到 memory |
| Memory tool description | 用户与环境事实均 `target=memory` |

## Prompt contract (chat)

Stable prefix roughly:

1. SOUL.md body（身份与风格）
2. Short product boundary（可选 3–5 行，防与用户资料混淆）
3. `## Durable Memory` ← MEMORY.md
4. Tool / harness rules
5. Dynamic: retrieval hits（sessions / local docs / shibei）— labeled as 用户相关资料，非灵犀身份

## Migration & compatibility

- One-shot profile → MEMORY.md as above
- Existing tests that assert profile injection / `/api/profile` must be updated or deleted
- Briefing / sync that call `ProfileService.get_view()`: return MEMORY.md-derived stub or empty markdown so callers don’t crash；no UI exposure
- Hermes import: still MEMORY.md only（already true）

## Testing

- Unit: migration appends profile once； second boot no duplicate
- Unit: background PUT persists and effective flags default true
- API: durable memory GET/PUT； profile endpoints gone/410
- Chat: system prompt contains MEMORY + SOUL, not「用户画像」专段
- UI smoke（optional）：memory pane has toggles + editor； no profile nav
- Identity: with custom SOUL, intro uses SOUL content

## Rollout

1. Backend: agent.json background + effective settings + migration
2. Retarget think / summarizer / chat write paths
3. Prompt + identity/SOUL wiring
4. Settings UI
5. Deprecate profile APIs + fix tests
6. Verify: `uv run pytest && uv run ruff check src tests`（typed API → `mypy src`）

## Open questions (resolved)

| Q | A |
|---|---|
| 去掉画像深度？ | B 彻底合并（实现路径 2） |
| 后台任务默认？ | **开** |
| SOUL vs identity.py？ | SOUL 为人设主源；identity 只做路由/作者短答 |

## Out of scope follow-ups

- Delete `ProfileService` / `user_profile_store` modules entirely
- Raise MEMORY.md cap further / structured sections UI
- Separate「作者信息」设置页
