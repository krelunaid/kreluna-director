#!/usr/bin/env bash
# Crea Kreluna Director.app e lo zip scaricabile per Mac.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/dist-macos"
APP="$OUT/Kreluna Director.app"
RES="$APP/Contents/Resources/app"

echo "Compilo la dashboard…"
bash "$ROOT/scripts/lib/build-web.sh"

rm -rf "$OUT"
mkdir -p "$APP/Contents/MacOS" "$RES"

cp "$ROOT/packaging/macos/Info.plist" "$APP/Contents/Info.plist"
cp "$ROOT/packaging/macos/Kreluna" "$APP/Contents/MacOS/Kreluna"
chmod +x "$APP/Contents/MacOS/Kreluna"

bash "$ROOT/scripts/lib/copy-app-tree.sh" "$RES"

echo "Includo Python nell'app (non serve installarlo)…"
python3 "$ROOT/scripts/lib/bundle_python.py" macos-arm64 "$APP/Contents/Resources/python-arm64"
python3 "$ROOT/scripts/lib/bundle_python.py" macos-x64 "$APP/Contents/Resources/python-x64"

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

cp "$ROOT/packaging/macos/LEGGIMI-MAC.txt" "$OUT/LEGGIMI-MAC.txt"
cp "$ROOT/packaging/macos/1-SE-DICE-CESTINO.txt" "$OUT/1-SE-DICE-CESTINO.txt"
cp "$ROOT/packaging/macos/Apri-me.html" "$OUT/Apri-me.html"
cp "$ROOT/packaging/macos/Installa Kreluna.command" "$OUT/Installa Kreluna.command"
chmod +x "$OUT/Installa Kreluna.command"

xattr -cr "$APP" >/dev/null 2>&1 || true

(
  cd "$OUT"
  zip -qry -y "Kreluna-Director-Mac.zip" \
    "Kreluna Director.app" \
    "Installa Kreluna.command" \
    "1-SE-DICE-CESTINO.txt" \
    "Apri-me.html" \
    "LEGGIMI-MAC.txt"
)

python3 - "$OUT/Kreluna-Director-Mac.zip" <<'PY'
import hashlib, sys
from pathlib import Path
path = Path(sys.argv[1])
digest = hashlib.sha256(path.read_bytes()).hexdigest()
path.with_suffix(".zip.sha256").write_text(digest + "  " + path.name + "\n")
print(digest)
PY

echo "Pronto: $OUT/Kreluna-Director-Mac.zip"
ls -lh "$OUT/Kreluna-Director-Mac.zip"
