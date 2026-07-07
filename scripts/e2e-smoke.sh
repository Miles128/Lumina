#!/usr/bin/env bash
# Lumina E2E: API smoke + Playwright UI (isolated data dir, port 8766).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH=src
export LUMINA_DATA_DIR="${LUMINA_DATA_DIR:-/tmp/lumina-e2e-smoke-$$}"
export LUMINA_E2E_PORT="${LUMINA_E2E_PORT:-8766}"
export SECRETARY_AUTO_SYNC_ENABLED=false
export SECRETARY_BRIEFING_ENABLED=false
export SECRETARY_THINK_ENABLED=false
export SECRETARY_MEMORY_SUMMARY_ENABLED=false
export PROMPT_GATE_ENABLED=false
export MCP_AUTO_FILESYSTEM=false

export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost,::1}"
export no_proxy="${no_proxy:-$NO_PROXY}"
echo "LUMINA_DATA_DIR=$LUMINA_DATA_DIR"
echo "LUMINA_E2E_PORT=$LUMINA_E2E_PORT"

RUN=(python3)
if command -v uv >/dev/null 2>&1; then
  RUN=(uv run python)
fi

if "${RUN[@]}" -c "import playwright" 2>/dev/null; then
  "${RUN[@]}" -m playwright install chromium 2>/dev/null || true
  PYTEST_PLAYWRIGHT="--browser chromium"
else
  echo "playwright not installed — skipping UI tests (uv sync --all-extras && uv run playwright install chromium)"
  PYTEST_PLAYWRIGHT=""
fi

ARGS=(-m e2e -v --tb=short)
if [[ -n "$PYTEST_PLAYWRIGHT" ]]; then
  ARGS+=(--browser chromium)
else
  ARGS+=(-m "e2e and not ui")
fi

if command -v uv >/dev/null 2>&1; then
  uv run pytest tests/e2e/ "${ARGS[@]}" "$@"
else
  python3 -m pytest tests/e2e/ "${ARGS[@]}" "$@"
fi
