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
printf 'APPL????' > "$APP/Contents/PkgInfo"
cp "$ROOT/packaging/macos/Kreluna" "$APP/Contents/MacOS/Kreluna"
chmod +x "$APP/Contents/MacOS/Kreluna"

bash "$ROOT/scripts/lib/copy-app-tree.sh" "$RES"

echo "Includo Python Apple Silicon (niente Intel)…"
python3 "$ROOT/scripts/lib/bundle_python.py" macos-arm64 "$APP/Contents/Resources/python-arm64"
rm -rf "$APP/Contents/Resources/python-x64"

echo "Creo l'icona visibile in Finder…"
python3 "$ROOT/scripts/lib/make_app_icon.py"
cp "$ROOT/packaging/macos/AppIcon.png" "$APP/Contents/Resources/AppIcon.png"
cp "$ROOT/packaging/macos/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

cp "$ROOT/packaging/macos/LEGGIMI-MAC.txt" "$OUT/LEGGIMI-MAC.txt"
cp "$ROOT/packaging/macos/1-SE-DICE-CESTINO.txt" "$OUT/1-SE-DICE-CESTINO.txt"
cp "$ROOT/packaging/macos/Apri-me.html" "$OUT/Apri-me.html"
ln -sfn /Applications "$OUT/Applicazioni"

xattr -cr "$APP" >/dev/null 2>&1 || true

(
  cd "$OUT"
  zip -qry -y "Kreluna-Director-Mac.zip" \
    "Kreluna Director.app" \
    "Applicazioni" \
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
