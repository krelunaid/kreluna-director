#!/usr/bin/env bash
# Copia soltanto il runtime Director necessario in DEST.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="${1:?Destinazione mancante}"
mkdir -p \
  "$DEST/apps/director-api" \
  "$DEST/apps/director-desktop" \
  "$DEST/apps/director-web" \
  "$DEST/packages" \
  "$DEST/policies"
cp -a "$ROOT/apps/director-api/app" "$DEST/apps/director-api/app"
cp "$ROOT/apps/director-desktop/kreluna_desktop.py" "$DEST/apps/director-desktop/"
cp "$ROOT/apps/director-desktop/native_window.py" "$DEST/apps/director-desktop/"
cp -a "$ROOT/apps/director-web/dist" "$DEST/apps/director-web/dist"
cp -a "$ROOT/packages/kreluna-shared" "$DEST/packages/kreluna-shared"
cp "$ROOT/policies/default.yaml" "$DEST/policies/default.yaml"
cp "$ROOT/policies/agents.yaml" "$DEST/policies/agents.yaml"
cp "$ROOT/policies/programs.yaml" "$DEST/policies/programs.yaml"

find "$DEST" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$DEST" -type f -name '*.pyc' -delete

if [[ ! -f "$DEST/apps/director-web/dist/index.html" ]]; then
  echo "Manca la dashboard compilata in $DEST" >&2
  exit 1
fi
