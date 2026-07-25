# Knowledge-work intent routing & grounding — Design

**Date:** 2026-07-26  
**Status:** Implemented (MVP)  
**Scope:** Optimize Auto profile routing (B) and prompt/grounding behavior (C) for writing, research, and office scenes — without a fourth primary profile or new workflow templates.

## Goals

1. Auto correctly distinguishes **draft-in-chat** vs **write-to-disk** for writing/office asks.
2. Research / writing / office turns get short, scene-specific system appendices (same pattern as `WEB_RESEARCH_APPENDIX`).
3. Light grounding retries for research (must retrieve) and office (must read cited docs), sharing the existing retry budget.
4. Keep Ask / Plan / Build as the only permission boundary; intent never grants write/shell/spawn.

## Non-goals

- Fourth primary profile / `mode: primary` Writing mode
- New workflow DAG templates (research/writing/office demos) — deferred (layer A)
- New Office binary writers (docx/xlsx generators); disk writes stay on `file_write` / `patch`
- Multi-agent debate / swarm
- Extra LLM call for intent classification (rules only)
- Changing product positioning away from general Agent productivity

## Decisions (locked)

| Decision | Choice |
|----------|--------|
| Approach | Soft `task_intent` layer on top of profiles |
| Writing default | No path → Ask (chat draft); path / explicit save → Build |
| Office write-back | Same path/save rule as writing |
| Profile lock | Manual Ask/Plan/Build keeps hard tool filter; intent appendix may still inject |
| Workflow templates | Out of this spec |

## Concept model

`task_intent` is orthogonal to `AgentProfile`:

| Intent | Example user language |
|--------|----------------------|
| `research` | 调研、查资料、对比、深度研究、有哪些说法 |
| `writing` | 写文章、润色、改写、扩写、提纲（non-code prose） |
| `office` | 读/整理 docx·pdf·xlsx、会议纪要、邮件草稿、表格汇总 |
| `code` | 现有开发语义 (refactor, shell, patch, …) |
| `none` | 闲聊 / uncategorized |

**Permission** = profile only.  
**Behavior** = intent → appendix + Auto preference + optional retry.

## Auto routing (B)

Adjust `resolve_auto_profile` precedence (conceptual order):

1. **Explicit mutate / shell / delegate** → `BUILD`  
   - Path or file extension detected (reuse existing path helpers) **and** save/write/overwrite/「生成到…」 semantics  
   - Or clear `file_write` / patch / git / shell / spawn markers  
2. **`writing` without persist signal** → `ASK`  
3. **Planning a piece of writing** (大纲 / 结构 / 章节方案, no execute) → `PLAN`  
4. **`research` or read-only `office`** → `ASK`  
5. **`office` + write-back** → `BUILD`  
6. Else existing Ask / Plan / Build marker rules

### Critical marker fix

Split the overloaded 「写」 in `_BUILD_MARKERS`:

- **Do not** treat alone as Build: 写一篇、润色、改写、扩写、起草、提纲  
- **Do** treat as Build: 写到 / 写入 / 保存到 / 保存为 / 覆盖 / 生成到 + path-or-filename, plus existing code/shell markers

`filesystem_turn` remains a Build force when the turn is about local FS mutation/inspection that already maps to Build today; pure 「总结这份 report.docx」 should route Ask + `office`, not Build solely because of a path mention used as a **read target**.

Clarification for path mentions:

| Signal | Route |
|--------|-------|
| Path + read/summarize/extract | Ask (+ office/research as matched) |
| Path + save/write/overwrite/create file | Build |
| No path + prose draft | Ask (+ writing) |

## Prompt appendices (C)

Inject after `profile_system_appendix`, only when intent ≠ `none` (and optionally when web research appendix already applies — concatenate, keep short).

| Intent | Appendix duties |
|--------|-----------------|
| `research` | At least one retrieval pass (web and/or Shibei when enabled); footnote citations; forbid “go look yourself”; reuse web-research retry helpers where applicable |
| `writing` | Structure first (title/outline) then body; no `file_write` without persist signal; may use user materials / Shibei; do not invent citations |
| `office` | Prefer `read_document` / `file_read`; structured outputs (纪要 / 要点 / 表格摘要); write-back only with path or explicit save language |

## Grounding retries (C)

Share the existing grounding + web + verify retry budget (no new unbounded loop):

| Intent | Retry trigger |
|--------|---------------|
| `research` | Reply asserts sources/facts but no retrieval tool used |
| `office` | Reply discusses document contents but neither `read_document` nor `file_read` (nor equivalent content-read) ran |
| `writing` | No forced tool retry; if reply claims “根据你的笔记/记忆” without memory/Shibei evidence → mark Unverified (existing grounding labels) |

## API / UX surface

- No new user-facing mode switch required for MVP.
- Optional later: show resolved intent as a subtle chip next to Auto — **out of MVP** unless trivial.
- Config: no new `agent.json` knobs required for MVP; if added later, belong under FR-52 harness family.

## Implementation sketch

| Area | Path |
|------|------|
| Intent rules | New `src/secretary/agent/task_intent.py` (enum + `resolve_task_intent`) |
| Auto routing | `src/secretary/agent/agent_profile.py` |
| Wire-up | `src/secretary/agent/chat_service.py` (resolve intent → appendix; pass into loop if needed) |
| Appendices + retry predicates | Prefer `knowledge_work.py` (or extend `web_research.py` only for research overlap — avoid bloating) |
| Tests | `tests/agent/test_agent_profile.py` + `tests/agent/test_task_intent.py` (+ retry cases if added) |

## Acceptance examples

| User message | Expected profile | Expected intent |
|--------------|------------------|-----------------|
| 帮我写一篇关于本地 Agent 的短文 | Ask | writing |
| 把上面保存到 `~/Notes/agent.md` | Build | writing |
| 调研一下 RAG 评测指标 | Ask | research |
| 总结这份 `report.docx` 的三点 | Ask | office |
| 把纪要写入 `minutes.md` | Build | office |
| 重构 loop.py | Build | code |

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Marker false positives (「写」 in code contexts) | Keep code/shell/path Build markers; writing markers only win when no code/persist signals |
| Path-as-read vs path-as-write confusion | Explicit persist lexicon + tests in table above |
| Appendix token bloat | Cap each appendix (~similar length to current web research block); one intent per turn |
| Intent conflicts (research + writing) | Priority: persist/code → writing-with-path → research → writing → office → none (document in code) |

### Intent priority (when multiple match)

1. Persist / mutate / shell / code signals → favor `code` or keep writing/office but **profile Build**  
2. `research` over bare `writing` if both “调研并写报告” without path → intent `research` (appendix research; Ask)  
3. `writing` over `office` for pure prose without document file types  
4. `office` when office file types or 纪要/邮件/表格 markers dominate  

## Spec self-review

- [x] No TBD/placeholder sections left for MVP decisions  
- [x] Consistent with PRD: no fourth profile; MCP/CLI-only integrations unchanged  
- [x] Non-goals explicit (templates, office writers)  
- [x] Scoped to B+C only  
- [x] Acceptance table testable without UI  

## Open follow-ups (explicitly later)

- Workflow templates that reuse the same intents (layer A)
- UI chip for resolved intent
- FR-52 knobs for intent sensitivity / appendix on-off
