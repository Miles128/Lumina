# FS naming + move + confirm diff — Design

**Date:** 2026-07-26  
**Status:** Implemented (MVP)  
**Scope:** (2) Pi-style rename `ls`/`grep`/`glob`, (3) `move` tool, (4) confirmation-card diff preview.

## Decisions

| Item | Choice |
|------|--------|
| Glob canonical name | `glob` + aliases `glob_files`, `find` |
| List / search | `ls`←`list_dir`, `grep`←`search_files` |
| Move | File only; no overwrite; always confirm |
| Diff | Backend preview on pause; UI `<pre>` in confirm bubble |

## Naming

| Canonical | Aliases |
|-----------|---------|
| `ls` | `list_dir` |
| `grep` | `search_files` |
| `glob` | `glob_files`, `find` |

Registry dual-register + Loop `_index_tools` bidirectional lookup. Grounding/profiles accept both.

## `move`

- Args: `from_path`, `to_path`
- Fail if source missing, not a file, or dest exists
- Create parent dirs of dest
- Confirm kind: `write_move` (or `write_modify`)
- Build/worker only

## Confirm diff

- `PendingConfirmation.diff_preview: str`
- `edit` / `write`: unified-ish or +/- preview, capped (~8KB / 200 lines)
- `ChatResponse.confirmation_diff`
- Desktop `appendConfirmation` renders escaped `<pre class="confirm-diff">`

## Non-goals

- Git tools, directory move, overwrite flag, MultiEdit, ApplyPatch
