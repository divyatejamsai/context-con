#!/usr/bin/env bash
# One command to bring the whole product up for a demo or a recording.
#
#   backend/scripts/demo_up.sh            # seed the fleet (live, .env modes), start backend + web UI
#   backend/scripts/demo_up.sh --no-fleet # skip the fleet run (store already seeded)
#
# 1. scripts/run_fleet.py onboards Sourced and the other AI employees into backend/data, runs payroll and each
#    agent's real job, so the console has real agents, verdicts and ledger entries to show.
# 2. Starts FastAPI on :8000 and Next.js on :3000. The UI runs Sourced as an AI employee
#    (NEXT_PUBLIC_AGENT_ID=sourced: passport check, Send Guard on drafts, ledger).
# Ctrl+C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/backend"

if [[ "${1:-}" != "--no-fleet" ]]; then
  echo "== seeding the AI employee fleet (CRUSTDATA_MODE=${CRUSTDATA_MODE:-from .env}, LLM_MODE=${LLM_MODE:-from .env})"
  python scripts/run_fleet.py || echo "!! fleet scorecard not all OK, see above (continuing)"
fi

echo "== backend on http://localhost:8000"
uvicorn app.main:app --port 8000 &
API=$!
trap 'kill $API 2>/dev/null' EXIT

for _ in $(seq 1 30); do curl -sf localhost:8000/api/health >/dev/null && break; sleep 0.5; done
curl -s localhost:8000/api/health; echo

cd "$ROOT/frontend"
[[ -d node_modules ]] || npm install
echo "== web UI on http://localhost:3000 (Sourced)  and  http://localhost:3000/console (Agaxes)"
NEXT_PUBLIC_DEFAULT_MODE=live NEXT_PUBLIC_AGENT_ID=sourced npm run dev
