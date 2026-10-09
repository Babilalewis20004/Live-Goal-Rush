"""Labelled, API-process-local Prometheus metrics (Phase 6).

The cross-process counters (`metrics.py`) are deliberately label-free: they are
pushed through Redis so worker and scheduler activity shows up in the API's
`/metrics`. Request and search latency only make sense per API process and need
labels and histograms, so they live in their own registry, appended to the
same `/metrics` response.

Label cardinality is bounded: `route` is the route *template*
(`/api/v1/articles/{slug}`), never the concrete URL, so a million different
slugs are one series.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

api_registry = CollectorRegistry()

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests handled", ["method", "route", "status"], registry=api_registry
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    registry=api_registry,
)
SEARCH_REQUESTS = Counter("search_requests_total", "Search requests", ["kind"], registry=api_registry)
SEARCH_EMPTY = Counter("search_empty_results_total", "Searches that returned nothing", registry=api_registry)
SEARCH_DURATION = Histogram(
    "search_duration_seconds",
    "Search latency (database work only)",
    ["kind"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
    registry=api_registry,
)
CELERY_QUEUE_LENGTH = Gauge("celery_queue_length", "Tasks waiting in the Celery queue", ["queue"], registry=api_registry)
MEDIA_BYTES = Counter("media_uploaded_bytes_total", "Bytes of accepted image uploads", registry=api_registry)

# -- Phase 7: state gauges refreshed on every scrape (see `refresh_state_gauges` in app/main.py) -----------------------
BUILD_INFO = Gauge("app_build_info", "Which release is running (value is always 1)", ["version", "git_sha", "environment"], registry=api_registry)
DEPENDENCY_UP = Gauge("app_dependency_up", "1 if the dependency answered its health check, else 0", ["dependency"], registry=api_registry)
DB_POOL = Gauge("db_pool_connections", "Database connection pool state for this API process", ["state"], registry=api_registry)
FAILED_JOBS = Gauge("failed_jobs_unresolved", "Background jobs that failed for good and nobody has resolved", registry=api_registry)
LIVE_DATA_AGE = Gauge(
    "football_live_data_age_seconds",
    "Age of the stalest live/half-time match's last provider sync (0 when nothing is live)",
    registry=api_registry,
)
WS_PER_PROCESS = Gauge("websocket_connections_process", "Open WebSocket connections held by this API process", registry=api_registry)


def render() -> bytes:
    return generate_latest(api_registry)
