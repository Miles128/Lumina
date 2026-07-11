# Lumina Desktop UI — Flat Minimal Redesign

**Date:** 2026-07-11  
**Status:** Approved  
**Approach:** CSS token consolidation (Option 1)

## Goal

Flatten the entire desktop UI toward Cursor / Codex minimalism: borderless controls, quiet chrome, no bird mascot. Keep a product fingerprint via a geometric lumen mark and a corner conversation mini-map.

## Decisions (locked)

| Topic | Choice |
| --- | --- |
| Visual baseline | Flat, borderless buttons, Cursor/Codex-like restraint |
| Brand mark | Geometric lumen light-dot +「灵犀」wordmark; remove bird logo |
| Distinctive signature | Conversation map as product fingerprint |
| Map default exposure | Corner mini-map (click → full map view) |
| Scope | Full desktop UI (chat + settings/skills/about + workspace) |
| Theme | Light primary; keep dark via CSS variable overrides |
| Implementation path | Token + CSS consolidation; reuse existing map engine |
| Messages | No avatars on either side; user messages light gray background; AI messages no background |

## Visual system

### Tokens (`desktop/ui/tokens.css`)

- Light defaults: `--bg #ffffff`, `--bg-subtle #fafafa`, `--text #111111`, `--text-secondary #666666`, `--text-tertiary #999999`.
- `--line` / `--line-strong` used only for structural dividers (topbar bottom, sidebar edge), never for buttons.
- Radii: controls ~`6px`, composer ~`12px`.
- No decorative `box-shadow` on chrome; focus via subtle background or accessible outline.
- Font stack: system UI (`system-ui`, SF Pro / PingFang SC fallbacks). Drop hard Inter dependency.
- Dark mode: same component rules; only variable values change.

### Borderless control rule

- Default `button`: `border: none; background: transparent`.
- Hover: light wash (`rgba(0,0,0,0.04)` / inverted in dark).
- Active / selected: slightly stronger wash or weight change — no stroke.
- Composer shell may use fill / extremely subtle inset to read as an input well; that is not a “button border.”

### Brand

- Remove `logo.png` bird from topbar, about panel, chat bot avatar, and related settings markup.
- Add `mark-lumen.svg`: ~14px radial grayscale light-dot (no face, no mascot).
- Topbar: lumen mark +「灵犀」.
- Favicon and about panel use the same mark.

## Shell layout

### Topbar

- Left: lumen + wordmark; model name in secondary color.
- Right: token usage as plain text; borderless hamburger menu.
- Keep `1px` structural bottom divider.

### Sidebar

- Thread list + new-thread / map icon buttons: borderless, hover wash.
- Active thread: subtle background highlight, no outline.

### Main column

- Welcome: large title + existing dotted prompt links; strip extra ornament.
- Messages:
  - **No avatars** for user or assistant (remove avatar DOM/CSS and `BOT_AVATAR_SRC` usage).
  - **User:** light gray background (`--bg-subtle`), modest radius, no border.
  - **Assistant:** no message background; text sits on canvas.
- Composer: filled rounded well; send / attach / mode / workspace chips borderless; focus deepens well fill slightly.

### Corner mini-map (signature)

- Persistent ~36×48 node preview at the chat main area’s top-right.
- Current node solid; others hollow; vertical connectors.
- Click opens the existing full conversation map view (reuse current map toggle / engine; do not rewrite graph logic).
- Single-node / no-branch: still show a single dot (keep the fingerprint visible).
- When full map is open, mini-map shows active wash state.

### Full-desktop parity

- `workspace.html` / `workspace.css`: same tokens and borderless controls.
- Settings / skills / about sheets: borderless close and tabs; about uses lumen mark.

## Out of scope

- Rewriting the conversation map / graph engine.
- Building a second component library or design-system package.
- Removing dark-mode variable capability.
- Marketing / landing page redesign.

## File touch list

| Area | Files |
| --- | --- |
| Tokens | `desktop/ui/tokens.css` |
| Chat chrome | `desktop/ui/chat.css`, `desktop/ui/topbar-lite.css`, `desktop/ui/index.html` |
| Chat behavior | `desktop/ui/chat.js` (avatars off; mini-map wired to existing map API) |
| Brand asset | `desktop/ui/mark-lumen.svg` (new); favicon references |
| Settings / about | `desktop/ui/settings.js` |
| Workspace | `desktop/ui/workspace.html`, `desktop/ui/workspace.css` |

## Acceptance criteria

1. All primary UI buttons render without visible borders in light and dark.
2. Topbar, about, and favicon show lumen mark; bird logo is gone from UI surfaces.
3. Messages have no avatars; user messages use light gray background; assistant messages have no background fill.
4. Corner mini-map is visible on the chat main column and opens the full map on click.
5. Workspace and settings/skills sheets visually match the chat shell token language.
6. Dark theme still switches via variables without broken contrast on core chrome.

## Implementation notes

- Prefer global button resets in tokens / shared base, then delete conflicting per-component border rules.
- Mini-map should call the same path as `#btn-map-sidebar` / existing map toggle rather than duplicating state machines.
- Keep diffs surgical: no drive-by refactors outside the visual system and the listed surfaces.
