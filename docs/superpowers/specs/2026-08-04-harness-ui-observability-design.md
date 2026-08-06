# Harness UI Observability — Design

**Date:** 2026-08-04  
**Status:** Approved for implementation  
**Scope:** Settings harness knobs, detailed thinking expand, context snapshot in chat UI

## Goals

1. Deepen **Settings → Harness** so more runtime knobs are adjustable in the UI (no chat quick-chips).
2. Make **thinking / progress** content fully readable via existing click-to-expand (no hard truncation when expanded).
3. Show **how much context** was sent and the **full assembled messages text** via a button on the right artifact panel.

## Decisions

| Topic | Choice |
|-------|--------|
| Tunable params | Settings Harness only (option B) |
| Thinking UX | Keep click-to-expand; full text when open; expand-all (option C simplified) |
| Context content | D staged: P0 = usage + assembled messages; P1 = injection source tabs |
| Context transport | Embed `context_snapshot` in `ChatResponse` + optional progress SSE `context_ready` (no new GET API) |
| Context UI entry | Button on right `artifact-panel` head → panel mode shows full context |
| Layout | No new drawer / bottom split |

## Architecture

```
AgentLoop / aisuite
  → assemble messages (post-compaction)
  → emit progress kind=context_ready (once, optional)
  → ChatResponse.context_snapshot
       ↓
chat.js memory cache by thread_id
       ↓
artifact-panel mode=context renders list + usage
```

Thinking path unchanged structurally: progress tree click-to-expand; backend stops truncating **thought** text in progress details.

## P0 — Context snapshot

### Schema

```json
{
  "trace_id": "",
  "thread_id": "",
  "captured_at": "",
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "cache_hit_tokens": null,
    "cache_miss_tokens": null,
    "estimated_prompt_tokens": 0
  },
  "compaction": { "before_tokens": null, "after_tokens": null },
  "messages": [
    { "index": 0, "role": "system", "content": "...", "approx_tokens": 0 }
  ],
  "message_count": 0,
  "approx_total_tokens": 0
}
```

- Content = what the model actually saw (tool outputs already subject to `max_tool_output_chars`).
- Never include API keys.
- Capture after compaction; prefer final-turn assembled messages.

### Transport

- `ChatResponse.context_snapshot: ContextSnapshot | null`
- Progress: `ProgressKind` adds `context_ready`; payload carries the same snapshot (or a slim reference + UI uses response). Prefer putting full body on `ChatResponse`; SSE may carry the same object once for early panel refresh before HTTP returns.
- Frontend: in-memory cache per `thread_id`. Refresh clears cache (accepted for P0).

### Right panel UX

- `artifact-panel-head`: button「上下文」toggles `mode` between `documents` and `context`.
- Context mode: hide tree/preview; show usage strip + collapsible message list; empty state if no snapshot yet.
- Remember last mode in `localStorage` key `artifactPanelMode`.

## P0 — Thinking detail

### Backend

- Do not apply `_progress_detail_preview` (320 chars) to **thought** text.
- Tool args / tool output previews may remain truncated in progress SSE.
- If thought and args share one `detail` string, keep thought full and truncate args only.

### Frontend

- Collapsed label: keep ~96-char one-line preview.
- Expanded node: full text, scrollable, no second truncation.
- Progress panel header:「全部展开 / 全部折叠」.
- Align aisuite Runner path to emit thought nodes comparable to AgentLoop.

## P0 — Settings Harness

Group existing fields; add missing:

| Group | Fields |
|-------|--------|
| Loop & compaction | `max_tool_rounds`, `light_max_steps`, `compaction_max_tokens`, `compaction_keep_tail`, `max_tool_output_chars` |
| Thinking | `thinking_mode`, `reasoning_effort`, `strict_tools` |
| Runtime | **`runtime_backend`** (`aisuite` \| `legacy`) — already on `HarnessConfig`, expose in UI |
| Observability | `trace_retention`, `trace_retain_days` |
| Cross-links | Read-only hints to LLM `max_history_turns` and Delegation `permission_mode` |

Save via existing `PUT /api/agent/config`. No hard limits (e.g. `MAX_SPAWN_DEPTH`) exposed.

## P1 (out of this implementation slice)

- `injections[]` in snapshot (soul / memory / shibei / grounding) as separate tabs (still visible inside system message in P0).
- Persist snapshots to disk + optional GET for post-refresh history.
- Chat composer quick chips.

## Non-goals

- Independent `GET /api/chat/context/...` (explicitly rejected).
- New layout paradigms (side inspector drawer, bottom split).
- Cloud sync / multi-user ACL for snapshots.

## Acceptance

1. Harness settings show groups + persist `runtime_backend`.
2. Long thoughts (>320 / >96) fully visible when expanded; expand-all works.
3. Right panel「上下文」shows message list + totals matching the turn’s assembled prompt.
4. Snapshot arrives via chat response / SSE only.
5. Empty / thread-switch behavior correct.

## Testing

- Unit: snapshot builder; thought not truncated in progress; ChatResponse schema.
- API: chat completion includes `context_snapshot`.
- Manual: panel mode switch; thinking expand; refresh empties context cache.

## Risks

- Large snapshots on local chat responses — acceptable for harness debugging; add size guard later if needed.
- aisuite vs legacy thought richness — must align emit paths.
