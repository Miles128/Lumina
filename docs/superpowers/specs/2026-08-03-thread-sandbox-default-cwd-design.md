# Design: Thread sandbox as default cwd (no workspace)

**Date:** 2026-08-03  
**Status:** Approved for planning  
**Decision:** When no workspace is selected, use a per-thread soft sandbox under `{data_dir}/sandbox/{thread_id}/` instead of `$HOME`.

## Problem

If the chat request has no `working_dir` and `agent.json` `shell_working_dir` is empty, `ChatService._shell_working_dir()` falls back to `Path.home()`. Relative `list_dir` / `file_*` / `shell` then target the entire home directory — too broad and unsafe as a default scratch space.

## Goals

- Default cwd = a Lumina-owned directory when the user has not chosen a workspace.
- Isolate that directory **per chat thread**.
- Soft boundary only: change default cwd; do **not** jail absolute paths.
- Delete the sandbox when the thread is deleted.
- Minimal surface: small helper + wire into existing resolve / delete paths.

## Non-goals

- Hard jail / read-outside deny when no workspace is set.
- Reusing KnowledgeWorkspace (`Notes/` / `wiki/`) as the default cwd.
- Extending `code_exec` process soft-sandbox to all tools.
- TTL / background sweep of old sandboxes.
- UI “沙箱” chip badge (optional later; not required for v1).

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Lifecycle | Per thread: `{data_dir}/sandbox/{thread_id}/` |
| Boundary | Soft: relative → sandbox; absolute paths unchanged |
| Cleanup | On `delete_thread` only |
| Approach | New `ThreadSandbox` helper (not KnowledgeWorkspace / not code_exec guards) |

## Architecture

```text
Chat request (working_dir?, thread_id)
        │
        ▼
ChatService._shell_working_dir()
  1) explicit turn working_dir (chip) if valid directory
  2) agent.json shell_working_dir if non-empty and is a directory
  3) ThreadSandbox.ensure(thread_id)     ← new
        │
        ▼
{data_dir}/sandbox/{safe_thread_id}/     # lazy mkdir
   default cwd for list_dir / file_* / shell / code_exec workspace root

delete_thread(thread_id)
        │
        ▼
ThreadSandbox.remove(thread_id)          # best-effort rmtree
```

### New module

`src/secretary/agent/thread_sandbox.py`

| API | Behavior |
|-----|----------|
| `sandbox_root(data_dir: Path) -> Path` | `data_dir / "sandbox"` |
| `safe_thread_id(thread_id: str) -> str` | Keep `[A-Za-z0-9._-]`; replace others with `_`; empty → `"_default"` |
| `ensure(thread_id: str, data_dir: Path) -> Path` | `mkdir(parents=True)`, return resolved path under `sandbox_root` |
| `remove(thread_id: str, data_dir: Path) -> None` | `shutil.rmtree(..., ignore_errors=True)` on that thread dir only |

Path safety: resolved ensure/remove targets must stay under `sandbox_root` (reject escape after sanitize).

### Resolution priority

| Priority | Condition | cwd |
|----------|-----------|-----|
| 1 | Request `working_dir` is a non-empty existing directory | That path |
| 2 | `shell_working_dir` non-empty and is a directory | Config path |
| 3 | `thread_id` present (after sanitize) | `{data_dir}/sandbox/{safe_id}/` |
| 4 | No / empty `thread_id` | `{data_dir}/sandbox/_default/` |

Invalid chip path: keep current behavior (ignore + warn); fall through to 2 → 3/4. **Never** fall back to `$HOME` on the happy path.

`ensure` failure (permissions, etc.): log error; last-resort fallback `Path.home()` only in that failure case; optional progress warning.

`data_dir` comes from `Settings.resolved_data_dir()` (default `~/.lumina`).

### Interaction with existing features

- **Tools:** unchanged; they already take `working_dir` from ChatService.
- **Confirm policy:** unchanged (writes/shell still confirm as today).
- **`code_exec`:** `LUMINA_WORKSPACE` = current cwd (sandbox root when defaulted); temp write cwd inside code_exec unchanged.
- **KnowledgeWorkspace:** unrelated; remains `data_dir/workspace`.
- **Subagent worktrees:** unrelated; remain `~/.lumina/worktrees`.
- **`explicit_working_dir` preflight:** still true only when the request carried a non-empty `working_dir`; sandbox default does **not** count as explicit workspace selection.

## Prompt / UI

- `_build_workspace_block`: still lists the real cwd. When cwd is under `{data_dir}/sandbox/`, append one line:  
  `未指定工作区，当前为会话沙箱（相对路径写在此；绝对路径仍可用）。`
- Settings placeholder for shell cwd:  
  `留空则使用用户主目录` → `留空则使用当前会话沙箱`.
- Workspace chip clear: no fake path; no required “沙箱” badge in v1.

## Cleanup

- Hook: `ChatService.delete_thread` (or immediately inside `ChatThreadStore.delete_thread` via injected callback — prefer ChatService so data_dir stays in one place) calls `ThreadSandbox.remove`.
- Best-effort only; delete-thread API must not fail if rmtree fails.
- No cleanup on turn end; no TTL sweeper.

## Testing

| Case | Expect |
|------|--------|
| No chip, empty `shell_working_dir`, with `thread_id` | cwd = `sandbox/{thread_id}`, directory exists |
| Valid `shell_working_dir` | That path; sandbox not required |
| Explicit valid `working_dir` | That path wins |
| Invalid chip | Fall through to config/sandbox, not `$HOME` |
| `delete_thread` | Matching sandbox directory removed |
| `../` / path separators in `thread_id` | Sanitized; path stays under `sandbox_root` |
| Empty `thread_id` | `_default` sandbox |

## Out of scope follow-ups

- Hard jail or read-loose/write-tight modes.
- Sandbox badge on the workspace chip.
- Age-based cleanup of orphaned dirs (e.g. after crash without delete).

## Implementation touchpoints (for plan)

- Add `thread_sandbox.py` + unit tests.
- Change `ChatService._shell_working_dir` and `delete_thread`.
- Update settings placeholder string in `desktop/ui/settings.js`.
- Optionally mention in `docs/harness-design.md` / PRD tool cwd note (short).
