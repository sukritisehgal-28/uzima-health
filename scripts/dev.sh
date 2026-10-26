#!/usr/bin/env bash
# Start every backend service locally (no keys needed) and, if installed, the dashboard.
# Logs go to .logs/<service>.log. Ctrl+C stops everything.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }
PY=${PY:-.venv/bin/python}
mkdir -p .logs
pids=()
start() { # name module port
  "$PY" -m uvicorn "$2" --port "$3" --log-level warning > ".logs/$1.log" 2>&1 &
  pids+=($!); echo "  $1  http://localhost:$3"
}
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
echo "Project Uzima (integrations switch on as keys appear in .env):"
start orchestrator services.orchestrator.app.main:app 8000
start sync_openai  services.sync_openai.app.main:app  8001
start sync_twilio  services.sync_twilio.app.main:app  8002
start collector    services.collector.app.main:app    8003
start handoff      services.handoff.app.main:app      8004
start public       services.public.app.main:app       8005
if [ -d apps/dashboard/node_modules ]; then
  (cd apps/dashboard && npm run dev -- --port 5173 > ../../.logs/dashboard.log 2>&1) & pids+=($!)
  echo "  dashboard    http://localhost:5173"
else
  echo "  dashboard    not installed: cd apps/dashboard && npm install"
fi
sleep 2 && curl -s localhost:8000/health && echo
wait
