#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if command -v uv >/dev/null 2>&1; then
  exec uv run python -m secretary.main "$@"
fi

export PYTHONPATH="$ROOT/src"
exec python3 -m secretary.main "$@"
