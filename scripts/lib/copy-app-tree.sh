#!/usr/bin/env bash
# Copia l'albero applicativo (senza dipendenze di sviluppo) in DEST.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="${1:?Destinazione mancante}"
mkdir -p "$DEST"
tar -C "$ROOT" -cf - \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'node_modules' \
  --exclude 'data' \
  --exclude 'dist-macos' \
  --exclude 'dist-windows' \
  --exclude '.pytest_cache' \
  --exclude '.cursor' \
  --exclude '*.pyc' \
  --exclude '.env' \
  --exclude 'kreluna_director.egg-info' \
  . | tar -C "$DEST" -xf -

if [[ ! -f "$DEST/apps/director-web/dist/index.html" ]]; then
  echo "Manca la dashboard compilata in $DEST" >&2
  exit 1
fi
