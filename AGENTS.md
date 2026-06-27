# AGENTS.md — Lumina

Local-first personal AI secretary: file access, memory, MCP, Feishu/reading/XHS sync, confirms before risky actions.

## Quick start

```bash
cd "/Users/sihai/Documents/My Projects/Lumina"
pip install -e ".[dev]"
cd desktop && npm install && npm start
# or: ./scripts/start-backend.sh && npm start
```

## Verification

```bash
pytest
ruff check src tests
mypy src
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

## Agent workflows

- Prefer minimal diffs; Lumina has many integrated subsystems (MCP, memory, Feishu).
- Run pytest before claiming API/agent loop changes are done.
