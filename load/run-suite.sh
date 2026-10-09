#!/usr/bin/env bash
# Run every k6 scenario against the running stack, warm first, and record what each container spent while it ran.
#
#   load/run-suite.sh "1 uvicorn worker" load/results/1w
#
# Resource use is read from the containers' cgroup counters before and after each run (CPU-seconds and peak memory),
# which costs nothing while the test runs. (`docker stats` was tried first: on Docker Desktop each call burns enough
# CPU to distort the very thing being measured.) Postgres connections and Redis state are sampled a few times mid-run.
#
# Output (in the results directory): <scenario>.json (k6 summary), <scenario>.log, <scenario>.res.json (resources).
# Then:  python load/summarize.py <results dir> "<label>"
set -euo pipefail
label="${1:?label}"
dir="${2:?results dir}"
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
mkdir -p "$dir"
PG_DB="${POSTGRES_DB:-football_perf}"
declare -A VUS=([home]=25 [live]=100 [search]=100 [spike]=100 [community]=100 [websocket]=1000)
SCENARIOS="${SCENARIOS:-home live search spike community websocket}"
CONTAINERS="api worker postgres redis"

cpu_usec() { docker exec "live-goal-$1-1" sh -c 'cat /sys/fs/cgroup/cpu.stat 2>/dev/null | awk "/^usage_usec/{print \$2}"' 2>/dev/null || echo 0; }
mem_peak() { docker exec "live-goal-$1-1" sh -c 'cat /sys/fs/cgroup/memory.peak 2>/dev/null || cat /sys/fs/cgroup/memory.current' 2>/dev/null || echo 0; }

for s in $SCENARIOS; do
  echo "== $label / $s: warm-up"
  bash load/run-k6.sh "$s" "$([ "$s" = websocket ] && echo 100 || echo 40)" 12s > /dev/null 2>&1 || true
  sleep 3

  declare -A before=()
  for c in $CONTAINERS; do before[$c]=$(cpu_usec "$c"); done
  t0=$(date +%s)
  echo "== $label / $s: measured run (${VUS[$s]} VUs)"
  bash load/run-k6.sh "$s" "${VUS[$s]}" 30s "$dir/$s.json" > "$dir/$s.log" 2>&1 &
  k6pid=$!
  pg_max=0; pg_active_max=0; redis_mb=0; redis_clients=0; queue=0
  sleep 20
  for i in 1 2 3 4; do   # sample mid-run, at the steady state
    row=$(docker exec live-goal-postgres-1 psql -U football -d "$PG_DB" -At -F, -c "select count(*), count(*) filter (where state='active') from pg_stat_activity where datname='$PG_DB'" 2>/dev/null || echo "0,0")
    c=${row%,*}; a=${row#*,}
    [ "$c" -gt "$pg_max" ] && pg_max=$c; [ "$a" -gt "$pg_active_max" ] && pg_active_max=$a
    info=$(docker exec live-goal-redis-1 redis-cli info 2>/dev/null | tr -d '\r')
    m=$(echo "$info" | awk -F: '/^used_memory:/{print int($2/1048576)}'); cl=$(echo "$info" | awk -F: '/^connected_clients:/{print $2}')
    [ "${m:-0}" -gt "$redis_mb" ] && redis_mb=$m; [ "${cl:-0}" -gt "$redis_clients" ] && redis_clients=$cl
    q=$(docker exec live-goal-redis-1 redis-cli llen football 2>/dev/null | tr -d '\r'); [ "${q:-0}" -gt "$queue" ] && queue=$q
    sleep 4
  done
  wait "$k6pid" || true
  t1=$(date +%s)
  res="{\"wall_s\": $((t1 - t0)), \"pg_conns_max\": $pg_max, \"pg_active_max\": $pg_active_max, \"redis_mb\": $redis_mb, \"redis_clients\": $redis_clients, \"queue_max\": $queue, \"containers\": {"
  first=1
  for c in $CONTAINERS; do
    after=$(cpu_usec "$c"); used=$(( (after - before[$c]) ))
    [ $first -eq 0 ] && res+=","; first=0
    res+="\"$c\": {\"cpu_cores_avg\": $(awk -v u="$used" -v w="$((t1 - t0))" 'BEGIN{printf "%.2f", u/1e6/w}'), \"mem_peak_mb\": $(( $(mem_peak "$c") / 1048576 ))}"
  done
  res+="}}"
  echo "$res" > "$dir/$s.res.json"
  grep -E "http_reqs\.|http_req_duration\.|server_errors\.|ws_connect" "$dir/$s.log" | head -4 || true
  echo "   resources: $res"
done
echo "done: $label"
