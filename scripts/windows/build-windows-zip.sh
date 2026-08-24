#!/usr/bin/env bash
# Crea lo zip installabile per Windows (eseguibile anche da Linux/Mac).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/dist-windows"
APP="$OUT/Kreluna Director"

echo "Compilo la dashboard…"
bash "$ROOT/scripts/lib/build-web.sh"

rm -rf "$OUT"
mkdir -p "$APP"
bash "$ROOT/scripts/lib/copy-app-tree.sh" "$APP"

cp "$ROOT/packaging/windows/Avvia.bat" "$APP/Avvia.bat"
cp "$ROOT/packaging/windows/Avvia.vbs" "$APP/Avvia.vbs"
cp "$ROOT/packaging/windows/Installa.ps1" "$OUT/Installa.ps1"
cp "$ROOT/packaging/windows/Installa.bat" "$OUT/Installa.bat"
cp "$ROOT/packaging/windows/LEGGIMI-WINDOWS.txt" "$OUT/LEGGIMI-WINDOWS.txt"
cp "$ROOT/scripts/windows/Install-KrelunaAgent.ps1" "$OUT/Install-KrelunaAgent.ps1"

python3 - "$OUT" <<'PY'
from pathlib import Path
import sys
from PIL import Image, ImageDraw

out = Path(sys.argv[1])
img = Image.new("RGB", (256, 256), (11, 18, 32))
draw = ImageDraw.Draw(img)
draw.rounded_rectangle((16, 16, 240, 240), radius=48, outline=(212, 175, 55), width=8)
draw.ellipse((70, 50, 186, 166), outline=(240, 215, 140), width=6)
ico = out / "Kreluna Director" / "kreluna.ico"
png = out / "Kreluna Director" / "kreluna.png"
img.save(png)
img.save(ico, sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
PY

(
  cd "$OUT"
  zip -qry "Kreluna-Director-Windows.zip" \
    "Kreluna Director" \
    "Installa.bat" \
    "Installa.ps1" \
    "Install-KrelunaAgent.ps1" \
    "LEGGIMI-WINDOWS.txt"
)

python3 - "$OUT/Kreluna-Director-Windows.zip" <<'PY'
import hashlib, sys
from pathlib import Path
path = Path(sys.argv[1])
digest = hashlib.sha256(path.read_bytes()).hexdigest()
path.with_suffix(".zip.sha256").write_text(digest + "  " + path.name + "\n")
print(digest)
PY

echo "Pronto: $OUT/Kreluna-Director-Windows.zip"
ls -lh "$OUT/Kreluna-Director-Windows.zip"
