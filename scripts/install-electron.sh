#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP="$ROOT/desktop"

export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
export npm_config_registry="https://registry.npmmirror.com"

cd "$DESKTOP"

echo "Installing Electron (using npmmirror)..."
for attempt in 1 2 3; do
  if npm install; then
    echo "Electron installed successfully."
    npx electron --version
    exit 0
  fi
  echo "Attempt $attempt failed, retrying in 5s..."
  rm -rf node_modules/electron
  sleep 5
done

echo "Install failed after 3 attempts. Check network or VPN, then rerun:"
echo "  ./scripts/install-electron.sh"
exit 1
