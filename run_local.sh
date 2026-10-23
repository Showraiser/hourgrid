#!/usr/bin/env bash
# One-command local demo: anvil chain + contracts + backend + frontend.
# Requires anvil (Foundry), Python 3.11+, Node 20+.  Stop everything with Ctrl+C.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "▶ contracts (prebuilt in contracts/artifacts; recompiled only if forge is installed)"
cd "$ROOT/contracts"
if command -v forge >/dev/null; then
  [ -d node_modules ] || npm install --silent
  forge build >/dev/null || echo "  forge build failed, using prebuilt artifacts"
fi

echo "▶ anvil (local chain on :8545)"
anvil --silent --block-time 1 &
PIDS=($!)
sleep 2

echo "▶ backend (:8000)"
cd "$ROOT/backend"
[ -d .venv ] || { python3 -m venv .venv; .venv/bin/pip install -q -r requirements.txt; }
[ -f .env ] || cp .env.example .env
CHAIN_ENABLED=1 .venv/bin/uvicorn hourgrid.api:app --port 8000 &
PIDS+=($!)

echo "▶ frontend (:3000)"
cd "$ROOT/frontend"
[ -d node_modules ] || npm install --silent
[ -f .env.local ] || cp .env.example .env.local
npm run dev &
PIDS+=($!)

trap 'kill "${PIDS[@]}" 2>/dev/null' EXIT
echo
echo "  Dashboard: http://localhost:3000    API docs: http://localhost:8000/docs"
echo "  (first start deploys contracts and onboards 25 meters: give it ~1 minute)"
wait
