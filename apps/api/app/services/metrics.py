"""Minimal metrics abstraction (Phase 2 §27).

Tracks the counters/gauges the spec asks for as plain in-process integers
so tests (and any code that just wants "did this counter move") don't need
Prometheus running. When `prometheus_client` is installed (it's in
requirements.txt), the same increments also update collectors exposed by
`GET /metrics`.

Each process (the API, the worker, the scheduler) keeps its own in-process
counters, as before. As of Phase 5 a process that calls
`metrics.enable_aggregation(role, redis_client)` (the API lifespan and the
Celery worker/beat start-up hooks do) also pushes them to Redis, and
`GET /metrics` renders the combined, per-role view -- see
`metrics_aggregation.py`. Processes that never enable it (unit tests) behave
exactly as in Phase 2.
"""

from __future__ import annotations

try:
    from prometheus_client import Counter, Gauge

    _PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only if the dep is missing
    _PROMETHEUS_AVAILABLE = False


class Metrics:
    _COUNTER_NAMES = (
        "provider_requests_total",
        "provider_errors_total",
        "provider_rate_limited_total",
        "sync_jobs_total",
        "sync_jobs_failed_total",
        "cache_hits_total",
        "cache_misses_total",
        "websocket_messages_sent_total",
        "websocket_connections_opened_total",
        "websocket_disconnections_total",
        "notifications_sent_total",
        "notifications_failed_total",
        "notifications_deduplicated_total",
    )

    def __init__(self) -> None:
        self._counters: dict[str, int] = dict.fromkeys(self._COUNTER_NAMES, 0)
        self._websocket_connections = 0
        self._live_matches = 0
        self._sink = None

        if _PROMETHEUS_AVAILABLE:
            self._prom_counters = {
                name: Counter(name, name.replace("_", " ")) for name in self._COUNTER_NAMES
            }
            self._prom_websocket_connections = Gauge(
                "websocket_connections", "Currently connected WebSocket clients"
            )
            self._prom_live_matches = Gauge("live_matches", "Matches currently LIVE or HALFTIME")
        else:
            self._prom_counters = {}
            self._prom_websocket_connections = None
            self._prom_live_matches = None

    def enable_aggregation(self, role: str, redis_client) -> None:
        """Start pushing this process's counters/gauges to Redis under `role`."""
        from app.services.metrics_aggregation import RedisMetricsSink

        self._sink = RedisMetricsSink(role, redis_client)
        # publish the gauges' current values straight away
        self._sink.set_gauge("websocket_connections", self._websocket_connections)
        self._sink.set_gauge("live_matches", self._live_matches)

    def flush(self) -> None:
        """Force a push to Redis (e.g. before rendering /metrics)."""
        if self._sink is not None:
            self._sink.set_gauge("websocket_connections", self._websocket_connections)
            self._sink.flush()

    def _increment(self, name: str, amount: int = 1) -> None:
        self._counters[name] += amount
        if self._sink is not None:
            self._sink.add(name, amount)
        prom_counter = self._prom_counters.get(name)
        if prom_counter is not None:
            prom_counter.inc(amount)

    def provider_request(self) -> None:
        self._increment("provider_requests_total")

    def provider_error(self) -> None:
        self._increment("provider_errors_total")

    def provider_rate_limited(self) -> None:
        self._increment("provider_rate_limited_total")

    def sync_job_started(self) -> None:
        self._increment("sync_jobs_total")

    def sync_job_failed(self) -> None:
        self._increment("sync_jobs_failed_total")

    def cache_hit(self) -> None:
        self._increment("cache_hits_total")

    def cache_miss(self) -> None:
        self._increment("cache_misses_total")

    def websocket_message_sent(self, amount: int = 1) -> None:
        self._increment("websocket_messages_sent_total", amount)

    def websocket_connected(self) -> None:
        self._increment("websocket_connections_opened_total")
        self._websocket_connections += 1
        if self._sink is not None:
            self._sink.set_gauge("websocket_connections", self._websocket_connections)
        if self._prom_websocket_connections is not None:
            self._prom_websocket_connections.set(self._websocket_connections)

    def websocket_disconnected(self) -> None:
        self._increment("websocket_disconnections_total")
        self._websocket_connections = max(0, self._websocket_connections - 1)
        if self._sink is not None:
            self._sink.set_gauge("websocket_connections", self._websocket_connections)
        if self._prom_websocket_connections is not None:
            self._prom_websocket_connections.set(self._websocket_connections)

    def notification_sent(self, amount: int = 1) -> None:
        self._increment("notifications_sent_total", amount)

    def notification_failed(self, amount: int = 1) -> None:
        self._increment("notifications_failed_total", amount)

    def notification_deduplicated(self, amount: int = 1) -> None:
        self._increment("notifications_deduplicated_total", amount)

    def set_live_matches(self, count: int) -> None:
        self._live_matches = count
        if self._sink is not None:
            self._sink.set_gauge("live_matches", count)
        if self._prom_live_matches is not None:
            self._prom_live_matches.set(count)

    def snapshot(self) -> dict:
        return {
            **self._counters,
            "websocket_connections": self._websocket_connections,
            "live_matches": self._live_matches,
        }


metrics = Metrics()
