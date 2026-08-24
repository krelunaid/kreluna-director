#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/apps/director-web"
if command -v npm >/dev/null 2>&1; then
  if [[ ! -d node_modules ]]; then
    npm install
  fi
  npm run build
elif command -v pnpm >/dev/null 2>&1; then
  if [[ ! -d node_modules ]]; then
    pnpm install
  fi
  pnpm run build
else
  echo "Serve Node.js con npm o pnpm per compilare la dashboard." >&2
  exit 1
fi
