"""Cross-process metrics (Phase 5).

Until now every process (API, worker, scheduler) kept private counters, so
`/metrics` on the API could not show provider/sync activity from the worker.
Instead of Prometheus multiprocess mode (shared files, which don't span
containers), every process pushes its counters to Redis -- which all of them
already share -- and `/metrics` renders the combined view.

Layout:
- `football:metrics:counters:{role}`  hash, name -> monotonically increasing
  count, one hash per process *role* (api / worker / scheduler). Counters
  are never reset, so Prometheus `rate()` keeps working across restarts.
- `football:metrics:gauges:{role}:{pid}`  hash of this process's gauges,
  with a TTL: a crashed process's gauges expire instead of lingering, and
  the render sums the live ones.

Increments are buffered in-process and flushed at most once per
`FLUSH_INTERVAL` seconds, so a hot path (every cache hit) doesn't become a
Redis round trip. Everything is best-effort: a Redis outage never raises
into application code, it just leaves the local counters (and the buffered
increments, up to a cap) as they are.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

COUNTERS_PREFIX = "football:metrics:counters:"
GAUGES_PREFIX = "football:metrics:gauges:"
FLUSH_INTERVAL_SECONDS = 1.0
GAUGE_TTL_SECONDS = 90
_MAX_PENDING_NAMES = 1000

_HELP = {
    "provider_requests_total": "Football provider requests made",
    "provider_errors_total": "Football provider requests that failed",
    "provider_rate_limited_total": "Football provider requests answered 429",
    "sync_jobs_total": "Background sync jobs started",
    "sync_jobs_failed_total": "Background sync jobs that failed",
    "cache_hits_total": "Redis cache hits",
    "cache_misses_total": "Redis cache misses",
    "websocket_messages_sent_total": "WebSocket messages sent",
    "websocket_connections_opened_total": "WebSocket connections opened",
    "websocket_disconnections_total": "WebSocket disconnections",
    "notifications_sent_total": "Push notifications sent",
    "notifications_failed_total": "Push notifications that failed",
    "notifications_deduplicated_total": "Push notifications suppressed as duplicates",
    "media_uploads_total": "Images uploaded",
    "media_uploads_rejected_total": "Image uploads rejected by validation",
    "articles_published_total": "Articles published (manually or by schedule)",
    "scheduled_publish_total": "Articles published by the scheduler",
    "comments_created_total": "Comments posted",
    "comments_reported_total": "Comment reports filed",
    "reactions_total": "Reactions recorded",
    "poll_votes_total": "Poll votes cast",
    "celery_tasks_total": "Celery tasks finished",
    "celery_task_failures_total": "Celery tasks that failed",
    "payment_webhooks_stale_total": "Webhook events ignored because a newer event was already applied",
    "payment_webhooks_failed_total": "Webhook events that failed to process (the processor will redeliver)",
    "websocket_clients_evicted_total": "WebSocket clients dropped for not reading",
    "db_pool_exhausted_total": "Requests refused because every database connection was busy",
    "db_unavailable_total": "Requests that failed because the database was unreachable",
    "rate_limited_total": "Requests rejected by a rate limit",
    "login_failures_total": "Failed sign-in attempts",
    "account_deletions_total": "Accounts erased at the user's request",
    "websocket_connections": "Currently connected WebSocket clients",
    "live_matches": "Matches currently LIVE or HALFTIME",
}


class RedisMetricsSink:
    """Buffers counters in memory and pushes them to Redis.

    `inline=True` (Celery processes, which are synchronous anyway) pushes from whatever thread calls `add`, at most once a
    second. `inline=False` (the API) never touches Redis from `add`/`set_gauge`: those run on the event loop, and a
    synchronous Redis call there stalls *every* request for as long as Redis takes to answer -- with Redis stopped that
    froze the whole API, health checks included. The API flushes from a worker thread on a timer instead.
    """

    def __init__(self, role: str, client: Any, *, now: Callable[[], float] = time.monotonic, inline: bool = True) -> None:
        self.role = role
        self._client = client
        self._now = now
        self._inline = inline
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._pending: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, int] = {}
        self._gauges_dirty = False
        self._last_flush = 0.0

    def add(self, name: str, amount: int = 1) -> None:
        with self._lock:
            if name in self._pending or len(self._pending) < _MAX_PENDING_NAMES:
                self._pending[name] += amount
        self._maybe_flush()

    def set_gauge(self, name: str, value: int) -> None:
        with self._lock:
            self._gauges[name] = value
            self._gauges_dirty = True
        self._maybe_flush()

    def _maybe_flush(self) -> None:
        if self._inline and self._now() - self._last_flush >= FLUSH_INTERVAL_SECONDS:
            self.flush()

    def flush(self) -> None:
        """Push buffered increments and current gauges. Never raises. Safe to call from a thread."""
        self._last_flush = self._now()
        with self._lock:
            batch = {name: amount for name, amount in self._pending.items() if amount}
            gauges = dict(self._gauges)
            self._pending.clear()
        try:
            pipe = self._client.pipeline()
            for name, amount in batch.items():
                pipe.hincrby(f"{COUNTERS_PREFIX}{self.role}", name, amount)
            if gauges:
                key = f"{GAUGES_PREFIX}{self.role}:{self._pid}"
                pipe.hset(key, mapping={k: int(v) for k, v in gauges.items()})
                pipe.expire(key, GAUGE_TTL_SECONDS)
            pipe.execute()
        except Exception:
            logger.debug("Metrics flush to Redis failed; keeping buffered values", exc_info=True)
            with self._lock:  # put the increments back so nothing is lost (bounded by _MAX_PENDING_NAMES names)
                for name, amount in batch.items():
                    self._pending[name] += amount
            return
        self._gauges_dirty = False


def read_aggregate(client: Any) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    """(counters by role, gauges summed by role) from a *sync* Redis client."""
    counters: dict[str, dict[str, int]] = {}
    for key in client.scan_iter(match=f"{COUNTERS_PREFIX}*"):
        role = key.removeprefix(COUNTERS_PREFIX)
        counters[role] = {name: int(v) for name, v in client.hgetall(key).items()}
    gauges: dict[str, dict[str, int]] = {}
    for key in client.scan_iter(match=f"{GAUGES_PREFIX}*"):
        role = key.removeprefix(GAUGES_PREFIX).split(":", 1)[0]
        bucket = gauges.setdefault(role, {})
        for name, v in client.hgetall(key).items():
            bucket[name] = bucket.get(name, 0) + int(v)
    return counters, gauges


async def read_aggregate_async(client: Any) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    """Same as `read_aggregate` for the async client the API process uses."""
    counters: dict[str, dict[str, int]] = {}
    async for key in client.scan_iter(match=f"{COUNTERS_PREFIX}*"):
        role = key.removeprefix(COUNTERS_PREFIX)
        counters[role] = {name: int(v) for name, v in (await client.hgetall(key)).items()}
    gauges: dict[str, dict[str, int]] = {}
    async for key in client.scan_iter(match=f"{GAUGES_PREFIX}*"):
        role = key.removeprefix(GAUGES_PREFIX).split(":", 1)[0]
        bucket = gauges.setdefault(role, {})
        for name, v in (await client.hgetall(key)).items():
            bucket[name] = bucket.get(name, 0) + int(v)
    return counters, gauges


def render_prometheus(counters: dict[str, dict[str, int]], gauges: dict[str, dict[str, int]]) -> str:
    """Prometheus text exposition: one series per metric per `role` label, so
    dashboards can `sum by (name)` for the whole system or look at one role."""
    lines: list[str] = []

    def emit(kind: str, source: dict[str, dict[str, int]]) -> None:
        names = sorted({n for per_role in source.values() for n in per_role})
        for name in names:
            lines.append(f"# HELP {name} {_HELP.get(name, name.replace('_', ' '))}")
            lines.append(f"# TYPE {name} {kind}")
            for role in sorted(source):
                if name in source[role]:
                    lines.append(f'{name}{{role="{role}"}} {source[role][name]}')

    emit("counter", counters)
    emit("gauge", gauges)
    return "\n".join(lines) + "\n"
