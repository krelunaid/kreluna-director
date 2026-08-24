#!/usr/bin/env bash
# Crea Kreluna Agent.app per Mac (non è il Director).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/dist-macos-agent"
APP="$OUT/Kreluna Agent.app"
RES="$APP/Contents/Resources/app"

rm -rf "$OUT"
mkdir -p "$APP/Contents/MacOS" "$RES"

cp "$ROOT/packaging/macos-agent/Info.plist" "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"
cp "$ROOT/packaging/macos-agent/Kreluna" "$APP/Contents/MacOS/Kreluna"
chmod +x "$APP/Contents/MacOS/Kreluna"

bash "$ROOT/scripts/lib/copy-agent-tree.sh" "$RES"
cp "$ROOT/packaging/macos-agent/director.url" "$RES/director.url"
cp "$ROOT/packaging/macos-agent/director.url" "$APP/Contents/Resources/director.url"

echo "Includo Python Apple Silicon (niente Intel)…"
python3 "$ROOT/scripts/lib/bundle_python.py" macos-arm64 "$APP/Contents/Resources/python-arm64"
rm -rf "$APP/Contents/Resources/python-x64"

python3 "$ROOT/scripts/lib/make_app_icon.py"
cp "$ROOT/packaging/macos/AppIcon.png" "$APP/Contents/Resources/AppIcon.png"
cp "$ROOT/packaging/macos/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

cp "$ROOT/packaging/macos-agent/LEGGIMI-AGENT-MAC.txt" "$OUT/LEGGIMI-AGENT-MAC.txt"
cp "$ROOT/packaging/macos-agent/Apri-me.html" "$OUT/Apri-me.html"
ln -sfn /Applications "$OUT/Applicazioni"

xattr -cr "$APP" >/dev/null 2>&1 || true

(
  cd "$OUT"
  zip -qry -y "Kreluna-Agent-Mac.zip" \
    "Kreluna Agent.app" \
    "Applicazioni" \
    "Apri-me.html" \
    "LEGGIMI-AGENT-MAC.txt"
)

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
