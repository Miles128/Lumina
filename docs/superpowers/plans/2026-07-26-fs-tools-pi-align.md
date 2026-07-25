# FS Tools Pi Align Implementation Plan

> **For agentic workers:** completed with design `2026-07-26-fs-tools-pi-align-design.md`.

**Goal:** Expose Pi-aligned `read` / `write` / `edit` with legacy aliases and Pi-style unique edit semantics.

**Done:**
- [x] `edit_text.py` — LF/BOM/fuzzy + unique match
- [x] `ReadTool` / `WriteTool` / `EditTool` + aliases
- [x] Registry, confirmation, grounding, subagents, prompts, PRD
- [x] Loop alias index for legacy tool call names
- [x] Tests + `pytest` / `ruff`
