#!/usr/bin/env bash
# Crea Kreluna Director.app e lo zip scaricabile per Mac.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/dist-macos"
APP="$OUT/Kreluna Director.app"
RES="$APP/Contents/Resources/app"

echo "Compilo la dashboard…"
if [[ ! -d "$ROOT/apps/director-web/node_modules" ]]; then
  (cd "$ROOT/apps/director-web" && npm install)
fi
(cd "$ROOT/apps/director-web" && npm run build)

rm -rf "$OUT"
mkdir -p "$APP/Contents/MacOS" "$RES"

cp "$ROOT/packaging/macos/Info.plist" "$APP/Contents/Info.plist"
cp "$ROOT/packaging/macos/Kreluna" "$APP/Contents/MacOS/Kreluna"
chmod +x "$APP/Contents/MacOS/Kreluna"

mkdir -p "$RES"
# Copia il progetto senza dipendenze di sviluppo.
tar -C "$ROOT" -cf - \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'node_modules' \
  --exclude 'data' \
  --exclude 'dist-macos' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.cursor' \
  --exclude '*.pyc' \
  --exclude '.env' \
  . | tar -C "$RES" -xf -

# La dist della UI serve a runtime; rsync l'ha copiata se presente.
if [[ ! -f "$RES/apps/director-web/dist/index.html" ]]; then
  echo "Manca la dashboard compilata" >&2
  exit 1
fi

python3 - "$OUT" <<'PY'
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

out = Path(sys.argv[1])
path = out / "Kreluna Director.app" / "Contents" / "Resources" / "AppIcon.png"
img = Image.new("RGB", (1024, 1024), (11, 18, 32))
draw = ImageDraw.Draw(img)
draw.rounded_rectangle((80, 80, 944, 944), radius=180, outline=(212, 175, 55), width=28)
draw.ellipse((300, 220, 724, 644), outline=(240, 215, 140), width=18)
font = ImageFont.load_default()
draw.text((430, 720), "KRELUNA", fill=(244, 239, 228), font=font)
img.save(path)
PY

cat > "$OUT/LEGGIMI-MAC.txt" <<'TXT'
KRELUNA DIRECTOR PER MAC
========================

1. Fai doppio clic su "Installa Kreluna.command"
   oppure trascina "Kreluna Director.app" nella cartella Applicazioni.

2. Apri Kreluna Director (doppio clic).
   La prima volta macOS può dire che l'app è di uno sviluppatore non identificato.
   Allora: clic destro sull'app → Apri → Apri.

3. Entra con:
   email:    andrea@studio.demo
   password: demo

Serve Python 3.11 o più nuovo (https://www.python.org/downloads/macos/).
La prima apertura scarica i componenti e può richiedere uno o due minuti.

Questa è la demo: fattura finta, non F24 veri.
TXT

cat > "$OUT/Installa Kreluna.command" <<'TXT'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
osascript -e 'display notification "Installo Kreluna nelle Applicazioni…" with title "Kreluna Director"'
cp -R "$DIR/Kreluna Director.app" "/Applications/"
xattr -dr com.apple.quarantine "/Applications/Kreluna Director.app" >/dev/null 2>&1 || true
open "/Applications/Kreluna Director.app"
TXT
chmod +x "$OUT/Installa Kreluna.command"

# Rimuovi la quarantena dallo zip locale (utile dopo il download).
xattr -cr "$APP" >/dev/null 2>&1 || true

(
  cd "$OUT"
  zip -qry "Kreluna-Director-Mac.zip" "Kreluna Director.app" "Installa Kreluna.command" "LEGGIMI-MAC.txt"
)

echo "Pronto: $OUT/Kreluna-Director-Mac.zip"
ls -lh "$OUT/Kreluna-Director-Mac.zip"
