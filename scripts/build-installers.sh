#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
bash "$ROOT/scripts/macos/build-mac-app.sh"
bash "$ROOT/scripts/windows/build-windows-zip.sh"
echo
echo "Installers:"
ls -lh "$ROOT/dist-macos/Kreluna-Director-Mac.zip" "$ROOT/dist-windows/Kreluna-Director-Windows.zip"
