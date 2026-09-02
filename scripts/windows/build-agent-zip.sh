#!/usr/bin/env bash
# Zip Windows: solo Agent, da installare sui PC dello studio (non il cervello).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/dist-agents"
APP="$OUT/Kreluna Agent"
BUILD_PYTHON="python3"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  BUILD_PYTHON="$ROOT/.venv/bin/python"
fi

rm -rf "$OUT"
mkdir -p "$APP"
bash "$ROOT/scripts/lib/copy-agent-tree.sh" "$APP"

echo "Includo Python nell'Agent Windows…"
"$BUILD_PYTHON" "$ROOT/scripts/lib/bundle_python.py" windows-x64 "$APP/runtime"

cp "$ROOT/packaging/windows-agent/Installa-Agent.ps1" "$OUT/Installa-Agent.ps1"
cp "$ROOT/packaging/windows-agent/LEGGIMI-AGENTI.txt" "$OUT/LEGGIMI-AGENTI.txt"
cp "$ROOT/packaging/windows-agent/director.url" "$OUT/director.url"

"$BUILD_PYTHON" - "$OUT" <<'PY'
from pathlib import Path
import sys

out = Path(sys.argv[1])
roles = [
    ("pc-fatture", "PC-FATTURE"),
    ("pc-f24", "PC-F24"),
    ("pc-contabilita", "PC-CONTABILITA"),
    ("pc-camerali", "PC-CAMERALI"),
    ("pc-contratti", "PC-CONTRATTI"),
    ("pc-durc", "PC-DURC"),
    ("pc-visure", "PC-VISURE"),
]
for role, display in roles:
    bat = out / f"Installa {display}.bat"
    bat.write_text(
        "\r\n".join(
            [
                "@echo off",
                f"title Installa Kreluna Agent {display}",
                (
                    'powershell -NoProfile -ExecutionPolicy Bypass -File '
                    '"%~dp0Installa-Agent.ps1"'
                    f" -Role {role} -DisplayName {display}"
                ),
                "if errorlevel 1 pause",
                "",
            ]
        ),
        encoding="ascii",
    )
generic = out / "Installa Kreluna Agent.bat"
generic.write_text(
    "\r\n".join(
        [
            "@echo off",
            "title Installa Kreluna Agent",
            'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Installa-Agent.ps1"',
            "if errorlevel 1 pause",
            "",
        ]
    ),
    encoding="ascii",
)
print("installer bat:", len(roles) + 1)
PY

(
  cd "$OUT"
  zip -qry "Kreluna-Agenti-Windows.zip" \
    "Kreluna Agent" \
    "Installa-Agent.ps1" \
    "LEGGIMI-AGENTI.txt" \
    "director.url" \
    Installa*.bat
)

"$BUILD_PYTHON" - "$OUT/Kreluna-Agenti-Windows.zip" <<'PY'
import hashlib, sys
from pathlib import Path
path = Path(sys.argv[1])
digest = hashlib.sha256(path.read_bytes()).hexdigest()
path.with_suffix(".zip.sha256").write_text(digest + "  " + path.name + "\n")
print(digest)
PY

echo "Pronto: $OUT/Kreluna-Agenti-Windows.zip"
ls -lh "$OUT/Kreluna-Agenti-Windows.zip"
