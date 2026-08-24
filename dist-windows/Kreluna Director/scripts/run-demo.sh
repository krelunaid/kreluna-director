#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p data
export PYTHONPATH="$ROOT/packages/kreluna-shared/src:$ROOT/apps/director-api:$ROOT/apps/kreluna-agent"
export DIRECTOR_DATABASE_URL="${DIRECTOR_DATABASE_URL:-sqlite+aiosqlite:///./data/kreluna.db}"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python3 -m pip install -q -e ".[dev]"

if [[ ! -d apps/director-web/node_modules ]]; then
  (cd apps/director-web && npm install)
fi

echo "Avvio Director API su :8080"
python3 -m uvicorn app.main:app --app-dir apps/director-api --host 127.0.0.1 --port 8080 &
API_PID=$!
sleep 2

echo "Avvio Agent"
python3 -m agent.main &
AGENT_PID=$!

cleanup() {
  kill "$AGENT_PID" "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "Avvio dashboard su :5173"
echo "Login: andrea@studio.demo / demo"
cd apps/director-web
npm run dev -- --host 127.0.0.1 --port 5173
