#!/usr/bin/env bash
# Kill the Celery worker hard (SIGKILL, as an OOM-kill or host loss would) while it is busy, restart it, and measure how long
# until every task has run. Tasks it held when it died are "unacked" in Redis and are redelivered after visibility_timeout.
#
#   load/worker_kill.sh            # needs the compose stack running with the dev Redis
set -uo pipefail
export MSYS_NO_PATHCONV=1
r() { docker exec live-goal-redis-1 redis-cli "$@" | tr -d '\r'; }
cat > /tmp/enqueue.py <<'PY'
from app.worker.celery_app import celery_app
for _ in range(60):
    celery_app.send_task("app.worker.analytics_tasks.generate_insights")
print("enqueued 60 tasks")
PY
docker stop live-goal-worker-1 > /dev/null
docker exec -i live-goal-api-1 python - < /tmp/enqueue.py
echo "queued while the worker was down: $(r llen football)"
docker start live-goal-worker-1 > /dev/null
sleep 14
echo "worker busy: queue=$(r llen football) unacked=$(r hlen unacked)"
docker kill live-goal-worker-1 > /dev/null
killed=$(date +%s)
echo "worker SIGKILLed: queue=$(r llen football) unacked=$(r hlen unacked)"
docker start live-goal-worker-1 > /dev/null
while true; do
  q=$(r llen football); u=$(r hlen unacked); elapsed=$(( $(date +%s) - killed ))
  [ "$q" = "0" ] && echo "t=${elapsed}s queue drained (unacked=$u)" && last_q0=${last_q0:-$elapsed}
  if [ "$q" = "0" ] && [ "$u" = "0" ]; then echo "t=${elapsed}s everything delivered and acknowledged: no task was lost"; break; fi
  [ "$elapsed" -gt 900 ] && echo "gave up after ${elapsed}s: queue=$q unacked=$u" && break
  sleep 15
done
echo "tasks finished by the worker (this container's life): $(docker logs live-goal-worker-1 2>&1 | grep -c '\"task_finished\"')"
