# AGENTS.md — Lumina

Local-first Agent productivity tool: harness (Turn/profiles/confirm), conversation map, memory, MCP, file access. Confirms before risky actions. Skill workflow DAG is planned (see docs/workflow-dag-design.md), not shipped.

Integrations: **standard MCP or CLI only** — do not add platform-specific connectors under `src/secretary/connectors/`. Legacy SyncService/connectors are frozen.

## Quick start

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
uv sync --extra dev
cd desktop && npm install && npm start
# or: ./scripts/start-backend.sh && npm start
```

Fallback (no uv): `pip install -e ".[dev]"`

## Verification

```bash
uv run pytest
uv run ruff check src tests
uv run mypy src
```

## Architecture

```
src/           FastAPI backend, AgentLoop, MCP, memory
desktop/       Electron shell
tests/
docs/          PRD + harness design — see docs/README.md
```

Product truth: `docs/PRD.md`. Do not follow superseded plans under `docs/superpowers/plans/` without checking PRD.

## Gotchas

- Backend + Electron are separate; start backend before desktop if scripts split.
- MCP config lives in secretary services — read existing patterns before adding servers.
- Python env: **uv** + `uv.lock` (`.venv/` local). CI uses `uv sync --all-extras`.

## Agent workflows

- Prefer minimal diffs; Lumina has many integrated subsystems (MCP, memory).
- Run pytest before claiming API/agent loop changes are done.
