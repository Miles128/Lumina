# 跨对话记忆系统设计

> 状态：设计稿 · 待实现  
> 目标：让 Lumina 在 dsh 上拥有**跨会话、可自动召回、可遗忘**的记忆，而不是只靠一份手工维护的 MEMORY.md。

## 1. 问题

当前只有一层：`MEMORY.md`（手工 curated 的长期事实），每轮整份注入。缺口：

- 对话里出现过的事实/决策/偏好，不主动写就丢了；
- 历史会话只能靠 dsh 的 session 检索，语义弱、跨会话成本高；
- Shibei 有语义检索，但需要显式调用，且只覆盖入库文档。

## 2. 分层（推荐方案 C：本地三层 + 可选 Shibei）

| 层 | 内容 | 存储 | 注入方式 |
|---|---|---|---|
| **L1 事实** | 稳定偏好、身份、项目常量 | `~/.lumina/memories/MEMORY.md` | 每轮注入（≤4K 字符） |
| **L2 情景** | 每次任务/决策的紧凑记录 | `~/.lumina/memory/episodes.jsonl` | 按当前问题检索 top-k 注入 |
| **L3 知识** | 文档、笔记、长文 | Shibei（MCP） | `shibei_context` 答前召回 |

不把三层合并成一个库：L1 要稳定、L2 要便宜、L3 要语义检索，混在一起会让注入 token 和更新策略互相打架。

## 3. 捕获（write path）

触发点：`session/event` 的 `turn/end`。

```
turn/end
  → 取本轮 user 文本 + assistant 最终文本 + tool 调用名 + 触碰文件
  → 启发式门禁（跳过寒暄、纯命令、< 80 字且无决策）
  → 生成 EpisodeRecord（≤600 字）
  → 内容 hash 去重
  → 追加 episodes.jsonl
  → 可选：抽出 1–3 条稳定事实 → 候选池
  → 稳定事实重复出现 ≥2 次或用户明确要求 → 晋升 MEMORY.md
```

`EpisodeRecord` 草案：

```json
{
  "id": "ep_20261025_...",
  "session_id": "session-...",
  "turn": 3,
  "ts": 1792866310000,
  "user": "把 Shibei 接进来",
  "summary": "决定用 dsh MCP client 接 Shibei，走 stdio，serverName=shibei。",
  "tags": ["shibei", "mcp", "decision"],
  "tools": ["read", "write"],
  "files": ["dsh/profile.patch.example.yml"],
  "facts": ["Lumina 用 dsh 的 mcp-client 接 Shibei"]
}
```

**抽取策略**（按里程碑升级）：

- M2：纯启发式——取 user 首句 + assistant 的结论句 + 工具/文件，拼摘要；不做额外 LLM 调用。
- M2.5：只对通过门禁的轮次调用一次 **utility 小模型** 抽 facts/tags（可配置预算，默认关闭）。
- M3：把重复出现的 fact 晋升 MEMORY.md，冲突时保留新值并记录旧值。

## 4. 召回（read path）

触发点：`agent/pre-step`（能拿到本轮 claimed user messages）。

```
pre-step
  → 取当前 user 文本
  → L1：MEMORY.md 已在 system prompt（不重复）
  → L2：BM25 / 关键词打分 episodes，取 top-k（k≤5，≤1.5K 字符）
  → L3：若 Shibei 可用且问题像个人背景类 → 模型按 prompt 规则调 shibei_context
  → 把 L2 命中作为 user-role context 注入（agent.inject / pre-step context）
  → 记录 recalled ids（trace / 可解释）
```

注入格式：

```
[Lumina memory] 与本轮相关的历史（来自 3 个会话）：
- 2026-10-20 · 项目：决定用 dsh 替代 Python harness
- 2026-10-24 · 偏好：中文回答，先结论
```

**为什么不让模型每次自己调 `search_memory`**：跨对话记忆的价值在「不用提醒也能想起来」。工具保留给显式查询，自动召回走 pre-step。

## 5. 存储与检索

- 启动：JSONL + 内存 BM25（零依赖，个人规模 < 5 万条足够）。
- 增长后：切 SQLite FTS5（`node:sqlite`，Node ≥22）或复用 Shibei 的 BM25。
- 单文件上限 + 定期 compaction（按时间/重要性淘汰）。
- 每条记录必须可删除：`memory_forget(id | session | before_date)`。

## 6. 隐私与可控

- 全部本地，默认不上传；不引入云端 embedding。
- `memory.capture: false` 可完全关闭自动捕获。
- `memory.recall: false` 可关闭自动召回，只留工具。
- 导出：`memory_export` 输出 JSONL；删除按 id/session/日期。
- Shibei 层沿用其本地存储与已有 `shibei_remember` 语义。

## 7. 里程碑

| 阶段 | 交付 | 验收 |
|---|---|---|
| M1（已交付） | MEMORY.md 注入 + `memory` / `search_memory` | 手工写入后下一轮能引用 |
| M2 | `turn/end` 自动捕获 episodes + `memory_forget` + 检索 | 新会话能搜到旧会话的决策 |
| M3 | `agent/pre-step` 自动召回 top-k | 不提醒也能引用历史偏好/决策 |
| M4 | Shibei 桥：把高价值 episode 写入 Shibei；召回时合并 L2/L3 | 跨设备/长文档语义命中 |

## 8. 非目标

- 云端同步 / 多用户 / 团队共享
- 每轮都调用 LLM 做抽取（默认关闭，按需开启）
- 自建向量数据库或 embedding 服务
- 把 dsh 的 session log 复制一份（L2 只存紧凑摘要，原文仍由 dsh 持久化）

## 9. 待决

1. L2 的抽取默认用启发式还是小模型？（成本 vs 质量）
2. 自动召回的注入点用 `agent/pre-step` + `agent.inject`，还是 `systemPrompt.context`？
3. episode 粒度：每轮一条，还是会话结束时汇总一条？
4. 事实冲突时：MEMORY.md replace，还是保留版本历史？
5. 是否把 L2 索引也交给 Shibei（减少一套存储）？
