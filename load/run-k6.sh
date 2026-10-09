#!/usr/bin/env bash
# Run one k6 scenario against the compose network and keep the summary.
#
#   load/run-k6.sh live 100 30s results/live-1worker.json
#
# Needs: the stack running (docker compose up -d), load/k6/world.json (apps/api/scripts/make_loadtest_data.py).
set -euo pipefail
scenario="${1:?scenario: home|live|search|spike|community|websocket}"
vus="${2:-100}"
duration="${3:-30s}"
out="${4:-}"
network="${COMPOSE_NETWORK:-live-goal_default}"
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1

args=(run --quiet /k6/scenarios.js)
[ -n "$out" ] && { mkdir -p "$(dirname "$out")"; args+=(--summary-export "/k6/out/$(basename "$out")"); mkdir -p load/k6/out; }

docker run --rm -i --network "$network" -v "$PWD/load/k6:/k6" \
  -e BASE="${BASE:-http://api:8000}" -e SCENARIO="$scenario" -e VUS="$vus" -e DURATION="$duration" \
  grafana/k6:latest "${args[@]}"
[ -n "$out" ] && mv "load/k6/out/$(basename "$out")" "$out"
exit 0
