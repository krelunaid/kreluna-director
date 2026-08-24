#!/usr/bin/env bash
# Copia solo l'Agent (niente Director, niente dashboard).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="${1:?Destinazione mancante}"
rm -rf "$DEST"
mkdir -p "$DEST/packages" "$DEST/apps" "$DEST/policies"
cp -a "$ROOT/packages/kreluna-shared" "$DEST/packages/kreluna-shared"
cp -a "$ROOT/apps/kreluna-agent" "$DEST/apps/kreluna-agent"
cp "$ROOT/policies/agents.yaml" "$DEST/policies/agents.yaml"
find "$DEST" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$DEST" -type d -name '.pytest_cache' -prune -exec rm -rf {} +
if [[ ! -f "$DEST/apps/kreluna-agent/agent/main.py" ]]; then
  echo "Copia Agent incompleta" >&2
  exit 1
fi
