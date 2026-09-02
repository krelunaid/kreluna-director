#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p data
export PYTHONPATH="$ROOT/packages/kreluna-shared/src:$ROOT/apps/director-api:$ROOT/apps/kreluna-agent"
export DIRECTOR_DATABASE_URL="${DIRECTOR_DATABASE_URL:-sqlite+aiosqlite:///./data/kreluna.db}"

find_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "$PYTHON_BIN"
    return
  fi
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
      command -v "$candidate"
      return
    fi
  done
  echo "Serve Python 3.11 o superiore (puoi indicarlo con PYTHON_BIN=/percorso/python3)." >&2
  exit 1
}

PYTHON="$(find_python)"
if [[ ! -d .venv ]]; then
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
  echo "La cartella .venv usa un Python troppo vecchio. Rinominala e rilancia la demo." >&2
  exit 1
fi
python3 -m pip install -q -e ".[dev]"

if command -v npm >/dev/null 2>&1; then
  WEB_INSTALL=(npm install)
  WEB_DEV=(npm run dev -- --host 127.0.0.1 --port 5173)
elif command -v pnpm >/dev/null 2>&1; then
  WEB_INSTALL=(pnpm install)
  WEB_DEV=(pnpm exec vite --host 127.0.0.1 --port 5173)
else
  echo "Serve npm oppure pnpm per avviare la dashboard." >&2
  exit 1
fi

if [[ ! -d apps/director-web/node_modules ]]; then
  (cd apps/director-web && "${WEB_INSTALL[@]}")
fi

echo "Avvio Director API su :8080"
python3 -m uvicorn app.main:app --app-dir apps/director-api --host 127.0.0.1 --port 8080 &
API_PID=$!
AGENT_PID=""

cleanup() {
  if [[ -n "$AGENT_PID" ]]; then
    kill "$AGENT_PID" 2>/dev/null || true
  fi
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT

API_READY=0
for _ in {1..40}; do
  if python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=1)' >/dev/null 2>&1; then
    API_READY=1
    break
  fi
  sleep 0.25
done
if [[ "$API_READY" != "1" ]] || ! kill -0 "$API_PID" 2>/dev/null; then
  echo "Il Director API non si è avviato." >&2
  exit 1
fi

echo "Avvio Agent"
KRELUNA_ENROLLMENT_CODE="$(python3 scripts/bootstrap_demo_agent.py)"
export KRELUNA_ENROLLMENT_CODE
python3 -m agent.main &
AGENT_PID=$!

echo "Avvio dashboard su :5173"
echo "Login: andrea@studio.demo / demo"
cd apps/director-web
"${WEB_DEV[@]}"
