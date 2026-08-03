# Design: aisuite as Lumina library base (C2)

**Date:** 2026-08-03  
**Status:** Phase 1 complete — vendored aisuite; Completions via Client; TurnRunner defaults to `runtime_backend=aisuite` (Runner for ask/plan-style turns; AgentLoop fallback when `spawn_subagent` / `force_web_first`); confirm pause/resume + grounding enforce on Runner path; DeepSeek thinking patches.  
**Decision:** Fork aisuite into `vendor/aisuite` as the LLM + Agents runtime base; keep Lumina Electron / ChatService / Turn / product harness on top.

## Problem

Lumina’s self-built `llm_client` + `AgentLoop` (~2.5k LOC core) duplicate what aisuite now provides: multi-provider Chat Completions and an Agents `Runner` with tool policies, state stores, and MCP. We want aisuite as the **library skeleton**, not a thin optional dependency, while preserving Lumina’s product differentiators.

## Goals

- Vendor a **fork** of [andrewyng/aisuite](https://github.com/andrewyng/aisuite) under `vendor/aisuite` (editable path dep).
- Lumina product harness stays: Electron UI, `ChatService`, Turn/SSE, conversation map, Shibei, profiles, IDP.
- Phase 1 must ship:
  1. Main chat + tool loop (including MCP tools already registered into Lumina)
  2. Confirm / pause / resume (write/shell)
  3. DeepSeek thinking / cache / `reasoning_content` replay
- Stable external contracts: `LoopResult`, `PendingConfirmation`, `ChatService.reply` / `confirm_action`, SSE progress kinds.
- Update PRD / harness-design: exception — **forked aisuite is allowed** as LLM+Agents base; still **do not** fork/embed Hermes · OpenCode · Pi · OpenWorker as product shell.

## Non-goals (phase 1)

- Replace Electron with OpenWorker/Tauri (that would be C1).
- Migrate subagent spawn/pause or grounding into aisuite Runner (phase 2).
- Replace TraceStore / HarnessConfig UI (keep compatible; no forced rewrite).
- Upstream every Lumina patch immediately (fork first; cherry-pick upstream later).

## Architecture

```text
Electron + FastAPI (Lumina product)
  ChatService · TurnRunner · profiles · SSE · confirm UX · Shibei
        │
        ▼
  AgentLoop facade (LoopResult / PendingConfirmation API preserved)
        │
        ▼
  aisuite bridge (secretary.agent.aisuite_*)
        ├── Client  → provider:model completions (DeepSeek fork patches)
        └── Runner  → multi-turn tool loop + RequireApproval → pause
              │
              ▼
        vendor/aisuite (fork)
```

### Phase 1 mapping

| Lumina concern | aisuite primitive | Adapter |
|---|---|---|
| `llm_client.chat_completion*` | `Client.chat.completions.create` | Model string `deepseek:…`; thinking kwargs |
| Tool schemas + execute | Agent `tools=` callables or JSON tools + manual loop | Wrap existing `Tool.execute` |
| Confirm pause | `RequireApprovalPolicy` + fork: `requires_input` pause | Map to `PendingConfirmation` |
| Resume after confirm | `Runner.continue_sync` / re-run with tool result | `resume_after_confirmation` |
| MCP | Keep Lumina `mcp_manager` → Tool registry (phase 1); optional aisuite MCP later | No dual MCP stacks in phase 1 |
| Progress SSE | Callback on tool/model steps | Bridge RunStep / loop hooks → `ProgressEvent` |

### Confirm / pause (fork patch)

Upstream aisuite denies tools in-policy and feeds an error string back to the model. Lumina needs **hard pause**. Fork change:

- When approval callback returns “needs human”, Runner stops with `status="requires_input"` and metadata `{pending_tool, arguments, …}` instead of auto-denying into the next model turn.
- Lumina adapter maps that to `PendingConfirmation` + `messages_snapshot`.

### DeepSeek (fork patch)

- Support custom `base_url` (not only `https://api.deepseek.com`).
- Pass through `thinking` / `reasoning_effort` / beta `strict_tools` when present.
- Preserve `reasoning_content` on assistant messages for tool-call turns.

## Migration strategy (strangler)

1. **Vendor + dep wiring** — installable fork, smoke import.
2. **LLM bridge** — `llm_client` delegates to aisuite `Client` (same public functions); existing AgentLoop keeps working.
3. **Runner bridge** — new runtime path behind harness flag `runtime_backend: "aisuite" | "legacy"` (default `aisuite` once green); confirm via fork pause.
4. **Delete legacy path** — only after phase 1 tests pass and phase 2 (subagent/grounding) planned.

## Testing

- Existing `tests/agent/test_llm_*`, confirm/stop-hook, loop tool-message tests must pass on bridge.
- New: `tests/agent/test_aisuite_bridge.py` (model mapping, thinking payload, approval→pending).
- Full suite: `uv run pytest && uv run ruff check src tests`.

## Risks

- aisuite Agents API still evolving; pin vendor commit SHA + Lumina patch notes in `vendor/aisuite/LUMINA_FORK.md`.
- OpenAI SDK dependency pulled in for DeepSeek provider — accept via aisuite extras.
- Dual loop temporarily increases surface; keep flag short-lived.
