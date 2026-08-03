# Lumina fork of aisuite

**Upstream:** https://github.com/andrewyng/aisuite  
**Pinned commit:** `cb29165b00f719cceae6a82ed4621cbcb79aaaf7`  
**Vendored:** 2026-08-03  

## Why

Lumina C2: use aisuite as the LLM + Agents library base while keeping Electron / ChatService / Turn product harness.

## Lumina patches (track here)

1. **DeepSeek provider** (`aisuite/providers/deepseek_provider.py`) — honor `base_url` from config (default `https://api.deepseek.com`); move `thinking` / `reasoning_effort` into OpenAI SDK `extra_body` (SDK rejects them as top-level create kwargs).
2. **Pause-on-approval** — `ApprovalRequiredError` in `utils/tools.py`; when `ToolPolicyDecision.metadata.pause_for_approval` is set, raise instead of deny-into-model. `client._tool_runner` attaches `pending_messages`; `Runner` returns `status=requires_input`.
3. **Packaging** — hatchling `pyproject.toml` for uv path install (`0.1.14+lumina`).

## Sync policy

Prefer cherry-pick / rebase onto upstream tags periodically. Do not vendor OpenWorker (`platform/`) into Lumina.
