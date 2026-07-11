# AGENTS.md — Lumina

Local-first Agent Harness: conversation orchestration, skill workflow orchestration, memory, MCP, file access. Confirms before risky actions.

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
```

## Gotchas

- Backend + Electron are separate; start backend before desktop if scripts split.
- MCP config lives in secretary services — read existing patterns before adding servers.
- Python env: **uv** + `uv.lock` (`.venv/` local). CI uses `uv sync --all-extras`.

## Agent workflows

- Prefer minimal diffs; Lumina has many integrated subsystems (MCP, memory).
- Run pytest before claiming API/agent loop changes are done.
