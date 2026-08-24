#!/bin/bash
# Installa Kreluna nelle Applicazioni e toglie il blocco "Cestino" di macOS.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
APP_SRC="$DIR/Kreluna Director.app"
APP_DST="/Applications/Kreluna Director.app"

osascript -e 'display notification "Installo Kreluna e tolgo il blocco di macOS…" with title "Kreluna Director"' >/dev/null 2>&1 || true

# Il "Sposta nel Cestino" arriva dalla quarantena del download. La togliamo tutta.
xattr -cr "$DIR" >/dev/null 2>&1 || true
xattr -cr "$APP_SRC" >/dev/null 2>&1 || true

if [[ ! -d "$APP_SRC" ]]; then
  osascript -e 'display dialog "Non trovo Kreluna Director.app accanto a questo file. Estrai prima lo zip." buttons {"OK"} default button 1 with title "Kreluna Director"' >/dev/null 2>&1 || true
  exit 1
fi

rm -rf "$APP_DST"
if command -v ditto >/dev/null 2>&1; then
  ditto "$APP_SRC" "$APP_DST"
else
  cp -R "$APP_SRC" "$APP_DST"
fi

xattr -cr "$APP_DST" >/dev/null 2>&1 || true
xattr -dr com.apple.quarantine "$APP_DST" >/dev/null 2>&1 || true

open "$APP_DST"
