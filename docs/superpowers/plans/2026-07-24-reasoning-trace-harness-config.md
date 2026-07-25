# Reasoning Trace + Harness Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship FR-51 (local reasoning/run trace: record · query · JSONL export) and FR-52 (harness tunable params wired through `agent.json` + Settings UI).

**Architecture:** Fan-out SSE `ProgressEvent` into append-only `TraceStore` (`~/.lumina/traces/{trace_id}.jsonl`). Nest `harness` on `AgentConfigDocument`; wire `max_tool_rounds` / `light_max_steps` / compaction / `trace_retention` into ChatService + AgentLoop. Settings tab `agent_harness` edits knobs; chat progress panel can load/export a turn’s trace.

**Tech Stack:** Python/FastAPI, pydantic, Electron `settings.js` / `chat.js`, pytest.

**Note:** Workflow HumanReview already owns FR-49/FR-50 — new IDs are **FR-51** (trace) and **FR-52** (harness config).

---

## File map

| File | Responsibility |
|------|----------------|
| `src/secretary/agent/harness_config.py` | `HarnessConfig` defaults + clamp helpers |
| `src/secretary/agent/trace_store.py` | Append / load / export / prune |
| `src/secretary/services/agent_config.py` | Persist `harness` on document |
| `src/secretary/api/deps.py` | Record progress into TraceStore |
| `src/secretary/api/routes_chat.py` | GET trace + JSONL export |
| `src/secretary/api/schemas.py` + `app.py` | Config API includes harness |
| `src/secretary/agent/turn_runner.py` / `loop.py` / `chat_service.py` | Wire knobs |
| `desktop/ui/settings.js` + `i18n.js` | Harness settings pane |
| `desktop/ui/chat.js` | Load/export trace from progress panel |
| `tests/agent/test_trace_store.py` | Trace persistence |
| `tests/services/test_agent_config.py` | Harness roundtrip |
| `tests/agent/test_chat_service.py` or new | max_steps from harness |

---

### Task 1: TraceStore (FR-51)

- [ ] Write failing tests in `tests/agent/test_trace_store.py`
- [ ] Implement `TraceStore` + event→node mapping
- [ ] Wire `build_progress_callback` + app state
- [ ] Add GET `/api/chat/traces/{trace_id}` and export endpoint

### Task 2: HarnessConfig (FR-52)

- [ ] Failing tests for harness roundtrip + max_steps wiring
- [ ] `HarnessConfig` on `AgentConfigDocument`
- [ ] Wire max_tool_rounds, light_max_steps, compaction_*, trace_retention
- [ ] Extend config API schemas

### Task 3: Desktop UI

- [ ] Settings nav `agent_harness` pane
- [ ] Chat: export / reload persisted thought nodes
- [ ] i18n strings

### Task 4: Docs + verify

- [ ] PRD status Planned → Done (MVP); fix FR-51/52 numbers
- [ ] `uv run pytest && uv run ruff check src tests`
