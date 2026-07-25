# FS tools Pi alignment (`read` / `write` / `edit`) — Design

**Date:** 2026-07-26  
**Status:** Implemented (MVP)  
**Scope:** Rename and harden filesystem write/edit tools to match Pi’s `read` / `write` / `edit` surface (behavior + schema), without forking Pi.

## Decisions (locked)

| Item | Choice |
|------|--------|
| Approach | B — rename to Pi names |
| Schema dialect | ① Pi: `path` + `oldText` / `newText` |
| Aliases | `file_read` → `read`, `file_write` → `write`, `patch` → `edit` |
| `edit` creates files? | No — create via `write` only |
| Confirmation | `write` and `edit` require confirm (same auth family) |
| Out of scope | Cursor `apply_patch`, PascalCase names, rename `list_dir` |

## Tool surface

| Canonical | Alias | Confirm |
|-----------|-------|---------|
| `read` | `file_read` | No |
| `write` | `file_write` | Yes |
| `edit` | `patch` | Yes |

Unchanged this round: `list_dir`, `search_files`, `glob_files`, `file_delete`.

## `edit` semantics (Pi-aligned)

1. Target file must exist.
2. Normalize LF for match; restore original line endings on write; strip BOM for match.
3. Exact match first, then light whitespace fuzzy (Pi-style).
4. Match must be **unique**; else fail with occurrence count.
5. No-op replacement → fail.
6. Accept legacy args `old_text` / `new_text` as aliases for `oldText` / `newText`.

## Compatibility

- Registry exposes both canonical and alias tool names (same execute path).
- Grounding / profiles / prompts / confirmation treat both names as equivalent.
- Content-read grounding: `read` and `file_read` both count.

## Non-goals

- Depend on `@mariozechner/pi-coding-agent`
- `replace_all` / `old_string` (Claude Code dialect)
- Unified diff apply_patch
