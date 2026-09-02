#!/usr/bin/env bash
# Crea Kreluna Director.app e lo zip scaricabile per Mac.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/dist-macos"
TEMP_ROOT="${TMPDIR:-/tmp}"
BUILD_OUT="$(mktemp -d "$TEMP_ROOT/kreluna-mac-build.XXXXXX")"
APP="$BUILD_OUT/Kreluna Director.app"
RES="$APP/Contents/Resources/app"
export COPYFILE_DISABLE=1

cleanup() {
  if [[ -n "$BUILD_OUT" && "$BUILD_OUT" == "$TEMP_ROOT"/kreluna-mac-build.* ]]; then
    rm -rf "$BUILD_OUT"
  fi
}
trap cleanup EXIT

echo "Compilo la dashboard…"
bash "$ROOT/scripts/lib/build-web.sh"

rm -rf "$OUT"
mkdir -p "$OUT"
mkdir -p "$APP/Contents/MacOS" "$RES"

cp "$ROOT/packaging/macos/Info.plist" "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"
cp "$ROOT/packaging/macos/Kreluna" "$APP/Contents/MacOS/Kreluna"
chmod +x "$APP/Contents/MacOS/Kreluna"

echo "Compilo la finestra nativa Kreluna…"
xcrun swiftc \
  -O \
  -target arm64-apple-macos12.0 \
  -framework AppKit \
  -framework WebKit \
  "$ROOT/packaging/macos/KrelunaWindow.swift" \
  -o "$APP/Contents/MacOS/KrelunaWindow"
chmod +x "$APP/Contents/MacOS/KrelunaWindow"

bash "$ROOT/scripts/lib/copy-app-tree.sh" "$RES"

echo "Includo il collegamento sicuro per i PC remoti…"
bash "$ROOT/scripts/lib/fetch-cloudflared.sh" macos-arm64 "$APP/Contents/Resources/cloudflared"

echo "Includo Python Apple Silicon (niente Intel)…"
python3 "$ROOT/scripts/lib/bundle_python.py" macos-arm64 "$APP/Contents/Resources/python-arm64"
rm -rf "$APP/Contents/Resources/python-x64"

echo "Creo l'icona visibile in Finder…"
"$APP/Contents/Resources/python-arm64/bin/python3.12" "$ROOT/scripts/lib/make_app_icon.py"
cp "$ROOT/packaging/macos/AppIcon.png" "$APP/Contents/Resources/AppIcon.png"
cp "$ROOT/packaging/macos/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

echo "Precompilo Python prima della firma…"
"$APP/Contents/Resources/python-arm64/bin/python3.12" -m compileall -q \
  "$APP/Contents/Resources/python-arm64/lib/python3.12" \
  "$RES/apps/director-api" \
  "$RES/apps/director-desktop" \
  "$RES/packages/kreluna-shared/src"

file "$APP/Contents/MacOS/KrelunaWindow" | grep -q 'arm64'
file "$APP/Contents/Resources/cloudflared" | grep -q 'arm64'

cp "$ROOT/packaging/macos/LEGGIMI-MAC.txt" "$BUILD_OUT/LEGGIMI-MAC.txt"
cp "$ROOT/packaging/macos/1-SE-DICE-CESTINO.txt" "$BUILD_OUT/1-SE-DICE-CESTINO.txt"
cp "$ROOT/packaging/macos/Apri-me.html" "$BUILD_OUT/Apri-me.html"
cp "$ROOT/packaging/macos/Disinstalla Kreluna.command" "$BUILD_OUT/Disinstalla Kreluna.command"
chmod +x "$BUILD_OUT/Disinstalla Kreluna.command"
ln -sfn /Applications "$BUILD_OUT/Applicazioni"

xattr -cr "$APP" >/dev/null 2>&1 || true
echo "Firmo il pacchetto Mac per il controllo dell'aggiornamento…"
/usr/bin/codesign --force --deep --sign - --timestamp=none "$APP"
/usr/bin/codesign --verify --deep "$APP"

(
  cd "$BUILD_OUT"
  zip -qry -y "Kreluna-Director-Mac.zip" \
    "Kreluna Director.app" \
    "Applicazioni" \
    "1-SE-DICE-CESTINO.txt" \
    "Apri-me.html" \
    "Disinstalla Kreluna.command" \
    "LEGGIMI-MAC.txt"
)
cp "$BUILD_OUT/Kreluna-Director-Mac.zip" "$OUT/Kreluna-Director-Mac.zip"

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
