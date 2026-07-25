# Knowledge-work Intent Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Soft `task_intent` (research/writing/office/code) steers Auto profile routing and scene appendices/retries without a fourth primary profile.

**Architecture:** Rules-only `resolve_task_intent` + `has_persist_signal`; Auto maps draft writing/office→Ask, persist→Build; `knowledge_work` appendices inject in ChatService; loop shares retry budget for research/office grounding.

**Tech Stack:** Python, existing AgentProfile / AgentLoop / pytest.

## Global Constraints

- No fourth primary profile; intent never grants write/shell/spawn.
- No extra LLM for classification; no new workflow templates; no new Office binary writers.
- Writing default: no path → Ask; path/explicit save → Build.

## File map

| File | Responsibility |
|------|----------------|
| `src/secretary/agent/task_intent.py` | `TaskIntent`, resolve, persist/code signals |
| `src/secretary/agent/knowledge_work.py` | Appendices + retry predicates |
| `src/secretary/agent/agent_profile.py` | Auto routing using intent |
| `src/secretary/agent/chat_service.py` | Inject appendix after profile appendix |
| `src/secretary/agent/loop.py` | Research/office retry in shared budget |
| `tests/agent/test_task_intent.py` | Intent + persist + acceptance table |
| `tests/agent/test_agent_profile.py` | Auto profile acceptance cases |
| `tests/agent/test_knowledge_work.py` | Appendix non-empty + retry predicates |

---

### Task 1: task_intent + Auto routing

- [x] Failing tests: acceptance table (intent + profile)
- [x] Implement `task_intent.py`; update `resolve_auto_profile` (split bare 「写」)
- [x] Green tests

### Task 2: knowledge_work appendices + wire ChatService

- [x] Failing tests for appendix selection
- [x] `knowledge_work.py` + inject in `_run_agent`
- [x] Green tests

### Task 3: Loop retries

- [x] Failing tests for research/office retry predicates
- [x] Wire into `loop.py` shared retry budget
- [x] Green + full verify (`pytest` + `ruff`)
