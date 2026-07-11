# Flat Minimal UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flatten Lumina desktop UI to Cursor/Codex-like minimalism with lumen mark + corner mini-map, no bird logo, no message avatars.

**Architecture:** Consolidate visual rules in `tokens.css`, strip borders in chat/topbar/workspace CSS, swap brand assets, wire corner mini-map to existing `.js-map-toggle` / ConversationMapModule.

**Tech Stack:** Electron desktop UI (HTML/CSS/vanilla JS)

---

### Task 1: Tokens + lumen mark

**Files:**
- Create: `desktop/ui/mark-lumen.svg`
- Modify: `desktop/ui/tokens.css`

- [ ] Add geometric light-dot SVG
- [ ] Update font, radii, hover wash vars; global `button` reset; dark variable overrides

### Task 2: Brand HTML surfaces

**Files:**
- Modify: `desktop/ui/index.html`, `desktop/ui/settings.js`, `desktop/ui/workspace.html`

- [ ] Replace logo.png with mark-lumen.svg (favicon, topbar, about)
- [ ] Add `#corner-mini-map` button with `.js-map-toggle` in chat column
- [ ] Bump CSS/JS cache query params

### Task 3: Flatten CSS

**Files:**
- Modify: `desktop/ui/chat.css`, `desktop/ui/topbar-lite.css`, `desktop/ui/workspace.css`

- [ ] Borderless sidebar/composer/toolbar buttons; remove avatar styles
- [ ] User bubble `--bg-subtle`; bot no fill; layout without avatar reserve
- [ ] Mini-map corner styles; about logo size for SVG mark

### Task 4: chat.js behavior

**Files:**
- Modify: `desktop/ui/chat.js`

- [ ] Remove avatar DOM from messages / streaming / confirmation
- [ ] Render/update corner mini-map from active path; refresh on thread changes

### Task 5: Verify

- [ ] Spot-check selectors; run `uv run pytest` + `uv run ruff check src tests` if Python untouched skip heavy; UI is frontend-only
