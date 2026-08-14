# AGENTS.md — Lumina

Local-first Agent productivity tool: harness (Turn/profiles/confirm), conversation map, memory, MCP, file access. Confirms before risky actions. Skill workflow DAG is planned (see docs/workflow-dag-design.md), not shipped.

Integrations: **standard MCP or CLI only** — platform connectors (飞书/微信读书/邮箱等) are removed. Do not add new modules under `src/secretary/connectors/`. Personal knowledge via Shibei / MEMORY.md / user MCP.

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

## 不造轮子纪律（No-reinventing rule）

协议/运行时层必须用库，禁止自研；产品策略层必须自研，禁止引库替代。

| 层 | 做法 | 代码位置 |
|---|---|---|
| LLM 协议 / tool 解析 / provider 适配 | **openai-agents SDK**（`agents_sdk_runtime.py`）| 边界文件，别处不 import SDK |
| LLM Chat Completions（utility/direct 路径） | **openai SDK**（同步 `OpenAI` client，`max_retries=0` 让外层统一重试）| `llm_client.py` |
| HITL 暂停/恢复/状态序列化 | SDK `interruptions` + `RunState`（`sdk_state`） | 同上 |
| 网络重试/退避 | SDK 内置（`llm_client` 自研重试是统一外层；openai client 内层已 `max_retries=0`） | `llm_client.py` |
| MCP 连接（stdio/SSE/HTTP） | 官方 `mcp` SDK；`mcp_manager` 只做工具桥接/审批（产品层，保留） | `mcp_manager.py` |
| Markdown 渲染/消毒 | markdown-it + DOMPurify | `desktop/ui/markdown.js` |
| 前端打包 | esbuild（未引入前保持 script 顺序 + `node --check`） | `desktop/ui/*` |

**必须自研（差异化，勿外包）**：grounding 校验、confirmation_policy、fs_jail、WriteGate、对话地图、TraceStore、Shibei 集成、Skill 编排。

**禁止**：import Hermes / opencode 产品 runtime（PRD 非目标）；新增手写 LLM 协议解析；vendor fork 上游库（最后手段）。

## Agent workflows

- Prefer minimal diffs; Lumina has many integrated subsystems (MCP, memory).
- Run pytest before claiming API/agent loop changes are done.
