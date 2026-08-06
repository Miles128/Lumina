# aisuite Base (C2 Phase 1) Implementation Plan

> **For agentic workers:** Execute task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Vendor a forked aisuite as Lumina’s LLM + Agents library base; ship phase 1 (chat+tools, confirm/pause, DeepSeek thinking) while keeping ChatService/Turn/Electron contracts.

**Architecture:** `vendor/aisuite` path dependency → `aisuite_bridge` Client factory → `llm_client` delegates to aisuite → AgentLoop later driven by Runner with fork pause-on-approval. Product harness stays above.

**Tech Stack:** Python 3.11+, uv, forked aisuite, existing pytest/ruff.

## Global Constraints

- Preserve `LoopResult` / `PendingConfirmation` / SSE progress contracts.
- Phase 1 does **not** move subagent or grounding into Runner.
- PRD exception: forked aisuite allowed; still no Hermes/OpenCode/Pi/OpenWorker shell fork.
- Spec: `docs/superpowers/specs/2026-08-03-aisuite-base-design.md`.

---

### Task 1: Vendor aisuite fork

**Files:**
- Create: `vendor/aisuite/` (package tree from upstream)
- Create: `vendor/aisuite/LUMINA_FORK.md`
- Modify: `pyproject.toml` (dependency + uv path source)
- Modify: `docs/PRD.md`, `docs/harness-design.md` (one-line exception)

- [ ] **Step 1:** Copy upstream `aisuite` Python package + its `pyproject.toml` / `LICENSE` / `README.md` into `vendor/aisuite`. Exclude `platform/`, `aisuite-js/`, `viewer-ui/`, large notebooks if present as top-level only noise — keep `aisuite/` package and tests optional.
- [ ] **Step 2:** Write `LUMINA_FORK.md` with upstream commit SHA and planned Lumina patches (DeepSeek thinking, pause-on-approval).
- [ ] **Step 3:** Add to root `pyproject.toml`:

```toml
dependencies = [
  # ...existing...
  "aisuite",
  "openai>=1.107.0",
]

[tool.uv.sources]
aisuite = { path = "vendor/aisuite", editable = true }
```

- [ ] **Step 4:** `uv sync --extra dev` and `python -c "import aisuite; from aisuite import Agent, Runner, Client; print(aisuite.__file__)"`
- [ ] **Step 5:** Patch PRD/harness-design exception text for forked aisuite.

---

### Task 2: Client bridge + model mapping

**Files:**
- Create: `src/secretary/agent/aisuite_bridge.py`
- Create: `tests/agent/test_aisuite_bridge.py`

**Interfaces:**
- Produces: `build_aisuite_client(config: LlmConfig) -> aisuite.Client`
- Produces: `to_aisuite_model(config: LlmConfig) -> str`  # e.g. `deepseek:deepseek-v4-flash`

- [ ] **Step 1:** Failing tests for model string mapping (deepseek base_url → `deepseek:`, openrouter → map or openai-compatible provider).
- [ ] **Step 2:** Implement bridge using provider configs `{provider: {api_key, base_url?}}`.
- [ ] **Step 3:** pytest the new file green.

---

### Task 3: DeepSeek fork patches

**Files:**
- Modify: `vendor/aisuite/aisuite/providers/deepseek_provider.py`
- Modify: `vendor/aisuite/LUMINA_FORK.md`

- [ ] **Step 1:** Allow `base_url` override from config.
- [ ] **Step 2:** Pass through `thinking` / `reasoning_effort` kwargs to create().
- [ ] **Step 3:** Document patch in `LUMINA_FORK.md`.

---

### Task 4: Route `llm_client` through aisuite Client

**Files:**
- Modify: `src/secretary/agent/llm_client.py`
- Test: `tests/agent/test_llm_client.py`, `tests/agent/test_llm_thinking_options.py`

- [ ] **Step 1:** Keep public signatures of `chat_completion`, `chat_completion_with_tools`, `apply_thinking_to_payload`, usage tracking.
- [ ] **Step 2:** Non-stream path: call aisuite `Client.chat.completions.create` with mapped model; convert response → `ChatCompletionResult` (including `reasoning_content`).
- [ ] **Step 3:** Stream path: keep httpx stream **or** aisuite stream if available; must not regress `on_delta`. Prefer keep httpx stream in phase 1 if aisuite streaming is awkward — document in bridge.
- [ ] **Step 4:** Run llm-related pytest green.

---

### Task 5: Pause-on-approval fork + AgentLoop Runner path

**Files:**
- Modify: `vendor/aisuite/aisuite/utils/tools.py` and/or `agents/runner.py`
- Create: `src/secretary/agent/aisuite_runtime.py`
- Modify: `src/secretary/agent/loop.py` or `turn_runner.py` (feature flag)
- Modify: `src/secretary/agent/harness_config.py` (`runtime_backend`)
- Test: confirm/stop-hook tests; new runtime tests

- [ ] **Step 1:** Fork: when policy signals human approval needed, return `requires_input` with pending tool metadata (do not auto-feed deny to model).
- [ ] **Step 2:** `aisuite_runtime.run_turn(...)` wraps tools as callables, uses `RequireApprovalPolicy` mapped from Lumina confirmation policy, returns `LoopResult`.
- [ ] **Step 3:** Wire `TurnRunner` to use aisuite runtime when `runtime_backend == "aisuite"`; default `"legacy"` until tests green, then flip default to `"aisuite"`.
- [ ] **Step 4:** `resume_after_confirmation` continues via runtime.
- [ ] **Step 5:** Full agent pytest subset for confirm + loop tools.

---

### Task 6: Verify + docs

- [ ] **Step 1:** `cd "/Users/sihai/Documents/My Projects/Lumina" && uv run pytest && uv run ruff check src tests`
- [ ] **Step 2:** `uv run mypy src` if typed surfaces changed.
- [ ] **Step 3:** Mark design status Implemented for phase 1 LLM bridge; note Runner flag state.

---

## Execution note

User approved immediate execution. Prefer **inline** task order 1→6. Do not commit unless asked.
