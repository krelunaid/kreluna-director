#!/usr/bin/env bash
# Crea Kreluna Agent.app per Mac (non è il Director).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/dist-macos-agent"
TEMP_ROOT="${TMPDIR:-/tmp}"
BUILD_OUT="$(mktemp -d "$TEMP_ROOT/kreluna-mac-agent-build.XXXXXX")"
APP="$BUILD_OUT/Kreluna Agent.app"
RES="$APP/Contents/Resources/app"
export COPYFILE_DISABLE=1

cleanup() {
  if [[ -n "$BUILD_OUT" && "$BUILD_OUT" == "$TEMP_ROOT"/kreluna-mac-agent-build.* ]]; then
    rm -rf "$BUILD_OUT"
  fi
}
trap cleanup EXIT

rm -rf "$OUT"
mkdir -p "$OUT"
mkdir -p "$APP/Contents/MacOS" "$RES"

cp "$ROOT/packaging/macos-agent/Info.plist" "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"
xcrun swiftc \
  -framework Cocoa \
  -framework ScreenCaptureKit \
  "$ROOT/packaging/macos-agent/KrelunaLauncher.swift" \
  -o "$APP/Contents/MacOS/Kreluna"

bash "$ROOT/scripts/lib/copy-agent-tree.sh" "$RES"
cp "$ROOT/packaging/macos-agent/director.url" "$RES/director.url"
cp "$ROOT/packaging/macos-agent/director.url" "$APP/Contents/Resources/director.url"

echo "Includo Python Apple Silicon (niente Intel)…"
python3 "$ROOT/scripts/lib/bundle_python.py" macos-arm64-agent "$APP/Contents/Resources/python-arm64"
rm -rf "$APP/Contents/Resources/python-x64"

"$APP/Contents/Resources/python-arm64/bin/python3.12" "$ROOT/scripts/lib/make_app_icon.py"
cp "$ROOT/packaging/macos/AppIcon.png" "$APP/Contents/Resources/AppIcon.png"
cp "$ROOT/packaging/macos/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

echo "Precompilo Python prima della firma…"
"$APP/Contents/Resources/python-arm64/bin/python3.12" -m compileall -q \
  "$APP/Contents/Resources/python-arm64/lib/python3.12" \
  "$RES/apps/kreluna-agent" \
  "$RES/packages/kreluna-shared/src"

cp "$ROOT/packaging/macos-agent/LEGGIMI-AGENT-MAC.txt" "$BUILD_OUT/LEGGIMI-AGENT-MAC.txt"
cp "$ROOT/packaging/macos-agent/Apri-me.html" "$BUILD_OUT/Apri-me.html"
ln -sfn /Applications "$BUILD_OUT/Applicazioni"

xattr -cr "$APP" >/dev/null 2>&1 || true
echo "Firmo Kreluna Agent…"
# Use the same Apple identity across installed updates to keep the designated
# requirement stable. Ad-hoc builds are only for development/testing.
/usr/bin/codesign --force --deep --sign "${KRELUNA_CODESIGN_IDENTITY:--}" --timestamp=none "$APP"
/usr/bin/codesign --verify --deep "$APP"

(
  cd "$BUILD_OUT"
  zip -qry -y "Kreluna-Agent-Mac.zip" \
    "Kreluna Agent.app" \
    "Applicazioni" \
    "Apri-me.html" \
    "LEGGIMI-AGENT-MAC.txt"
)
cp "$BUILD_OUT/Kreluna-Agent-Mac.zip" "$OUT/Kreluna-Agent-Mac.zip"

python3 - "$OUT/Kreluna-Agent-Mac.zip" <<'PY'
import hashlib, sys
from pathlib import Path
path = Path(sys.argv[1])
digest = hashlib.sha256(path.read_bytes()).hexdigest()
path.with_suffix(".zip.sha256").write_text(digest + "  " + path.name + "\n")
print(digest)
PY

echo "Pronto: $OUT/Kreluna-Agent-Mac.zip"
ls -lh "$OUT/Kreluna-Agent-Mac.zip"
