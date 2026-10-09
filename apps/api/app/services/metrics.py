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
        # Phase 6
        "media_uploads_total",
        "media_uploads_rejected_total",
        "articles_published_total",
        "scheduled_publish_total",
        "comments_created_total",
        "comments_reported_total",
        "reactions_total",
        "poll_votes_total",
        "celery_tasks_total",
        "celery_task_failures_total",
        # Phase 6b: analytics, predictions, billing
        "analytics_generation_total",
        "analytics_generation_failures_total",
        "prediction_generation_total",
        "prediction_evaluation_total",
        "insight_generation_total",
        "subscription_created_total",
        "subscription_renewed_total",
        "subscription_cancelled_total",
        "subscription_payment_failed_total",
        "payment_webhooks_total",
        "payment_webhooks_rejected_total",
        "premium_feature_usage_total",
        "premium_feature_denied_total",
        # Phase 7: operational signals the alert rules (monitoring/prometheus/alerts.yml) watch
        "payment_webhooks_stale_total",
        "payment_webhooks_failed_total",
        "websocket_clients_evicted_total",
        "db_pool_exhausted_total",
        "db_unavailable_total",
        "rate_limited_total",
        "login_failures_total",
        "account_deletions_total",
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

    def enable_aggregation(self, role: str, redis_client, *, inline: bool = True) -> None:
        """Start pushing this process's counters/gauges to Redis under `role`. The API passes `inline=False` and flushes
        from a background thread (`flush`), so a slow or dead Redis can never stall its event loop."""
        from app.services.metrics_aggregation import RedisMetricsSink

        self._sink = RedisMetricsSink(role, redis_client, inline=inline)
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

    def count(self, name: str, amount: int = 1) -> None:
        """Increment any registered counter by name (Phase 6b counters)."""
        self._increment(name, amount)

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

    def media_uploaded(self) -> None:
        self._increment("media_uploads_total")

    def media_upload_rejected(self) -> None:
        self._increment("media_uploads_rejected_total")

    def article_published(self, amount: int = 1) -> None:
        self._increment("articles_published_total", amount)

    def scheduled_publish(self, amount: int = 1) -> None:
        self._increment("scheduled_publish_total", amount)

    def comment_created(self) -> None:
        self._increment("comments_created_total")

    def comment_reported(self) -> None:
        self._increment("comments_reported_total")

    def reaction_recorded(self) -> None:
        self._increment("reactions_total")

    def poll_voted(self) -> None:
        self._increment("poll_votes_total")

    def celery_task(self, failed: bool = False) -> None:
        self._increment("celery_tasks_total")
        if failed:
            self._increment("celery_task_failures_total")

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
