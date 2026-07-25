# code_exec workspace sandbox — Design

**Date:** 2026-07-23  
**Status:** Accepted (MVP)  
**Scope:** Strengthen harness so the agent can solve problems by writing Python that runs in a soft sandbox.

## Goals

1. Sandbox **may read** the current workspace (`working_dir`).
2. Sandbox **must not write** the workspace; writes only under the temp exec cwd.
3. Harness prompts prefer `code_exec` for compute/parse/transform; iterate on non-zero exit.
4. After the user approves `code_exec` once in a session, further `code_exec` calls skip confirmation.
5. Ask profile gets `code_exec` (no workspace mutation). Plan stays without it.

## Non-goals

- Docker / seatbelt / OS isolation
- Electron UI changes
- pip install or network inside the sandbox
- Auto-writing sandbox outputs back to the workspace (use `file_write` / `patch`)

## Mechanism

- Bootstrap guards `open` (read: workspace ∪ sandbox; write: sandbox only), soft-blocks destructive `os`/`shutil` against the workspace, disables `socket`.
- Env `LUMINA_WORKSPACE` = resolved workspace root.
- Session flag `FileAuthService.session_code_exec` cleared when the ChatService process ends / session write-new clears.

## Profiles

| Profile | `code_exec` |
|---------|-------------|
| Build / Auto→Build | Yes (confirm then session grant) |
| Ask / Auto→Ask | Yes (same) |
| Plan | No |
| worker sub-agent | Yes |
