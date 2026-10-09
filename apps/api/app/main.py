import asyncio
import logging
import socket
import re
import time
import uuid
from contextlib import asynccontextmanager

from typing import Annotated

import asyncpg
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from redis import exceptions as redis_exceptions
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeoutError

from app.api.v1.router import api_router
from app.api.v1.websocket import router as websocket_router
from app.core import http_security
from app.core.config import settings
from app.core.production_checks import enforce as enforce_configuration
from app.core.logging_config import configure_logging, log_event, request_id_var
from app.core.redis_client import RedisService, get_redis_service
from app.db.session import get_db
from app.services import http_metrics
from app.services.metrics import metrics
from app.services.providers import get_provider
from app.services.seed import seed_database
from app.websocket.manager import manager
from app.websocket.pubsub_bridge import PubSubBridge

logger = logging.getLogger(__name__)


_PROBE_TIMEOUT_SECONDS = 2.0

# PostgreSQL SQLSTATE classes that mean "the server cannot serve this right now, try again" rather than "the query is wrong":
#   08 connection exception · 53 insufficient resources (e.g. 53300 too many connections) · 57 operator intervention
#   (57P01 shutting down, 57P03 starting up, 57014 cancelled by statement_timeout) · 40 transaction rollback (deadlock, serialisation)
_TRANSIENT_SQLSTATE_CLASSES = ("08", "53", "57", "40")


def _is_transient_sqlstate(exc: BaseException) -> bool:
    for candidate in (getattr(exc, "orig", None), getattr(getattr(exc, "orig", None), "__cause__", None), exc.__cause__):
        state = getattr(candidate, "sqlstate", None) or getattr(candidate, "pgcode", None)
        if isinstance(state, str) and state[:2] in _TRANSIENT_SQLSTATE_CLASSES:
            return True
    return False


async def _database_healthy(session: AsyncSession) -> bool:
    try:
        await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=_PROBE_TIMEOUT_SECONDS)
        return True
    except Exception:
        logger.warning("Database health check failed", exc_info=True)
        return False


async def _redis_healthy(redis: RedisService) -> bool:
    try:
        return bool(await asyncio.wait_for(redis.health_check(), timeout=_PROBE_TIMEOUT_SECONDS))
    except Exception:
        logger.warning("Redis health check failed", exc_info=True)
        return False


def _provider_configured() -> bool:
    """A cheap reachability signal, not a live network call on every health
    check (that would itself count against the provider's rate limit) --
    true if the configured provider constructed successfully (it requires
    an API key).""" 
    try:
        get_provider()
        return True
    except Exception:
        logger.warning("Provider is not configured correctly", exc_info=True)
        return False


async def _metrics_flusher(metrics) -> None:
    """Push this process's counters to Redis once a second from a worker thread (never from the event loop)."""
    while True:
        await asyncio.sleep(1)
        try:
            await asyncio.to_thread(metrics.flush)
        except Exception:
            logger.debug("Metrics flush failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await seed_database()
    except Exception:
        logger.exception("Startup seeding failed; continuing without a pre-warmed database")

    if settings.media_storage_backend.lower() == "s3":
        try:
            from app.services.storage import get_storage

            await get_storage().ensure_bucket()  # local MinIO starts empty; real S3/R2 buckets already exist
        except Exception:
            logger.warning("Could not verify the media bucket; uploads will fail until storage is reachable", exc_info=True)

    try:
        from app.core.redis_client import get_sync_redis_service
        from app.services.metrics import metrics

        metrics.enable_aggregation("api", get_sync_redis_service().raw, inline=False)
        flusher = asyncio.create_task(_metrics_flusher(metrics))
    except Exception:
        flusher = None
        logger.warning("Cross-process metrics unavailable; /metrics will show this process only", exc_info=True)

    bridge = PubSubBridge(redis=get_redis_service(), manager=manager)
    bridge.start()
    try:
        yield
    finally:
        await bridge.stop()
        if flusher is not None:
            flusher.cancel()


_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def route_template(scope: dict) -> str:
    """`/api/v1/articles/{slug}` for a request to `/api/v1/articles/some-story`.

    Built from the path and its matched path parameters, so every slug/id is one
    series. A request that matched no endpoint (a scanner probing random URLs) is
    `unmatched`, so metric cardinality cannot be driven up from outside."""
    if scope.get("endpoint") is None:
        return "unmatched"
    segments = scope.get("path", "").split("/")
    for name, value in (scope.get("path_params") or {}).items():
        segments = [f"{{{name}}}" if segment == str(value) else segment for segment in segments]
    return "/".join(segments) or "/"


def create_app() -> FastAPI:
    configure_logging()
    enforce_configuration(settings)  # staging/production refuse to start on unsafe configuration
    app = FastAPI(
        title="Football Livescore API",
        description="Provider-agnostic, real-time football livescore API.",
        version=settings.app_version,
        lifespan=lifespan,
        # The interactive docs and schema are a map of the attack surface; deployed environments omit them.
        docs_url=None if settings.is_deployed else "/docs",
        redoc_url=None if settings.is_deployed else "/redoc",
        openapi_url=None if settings.is_deployed else "/openapi.json",
    )

    http_security.configure(app)
    if settings.allowed_host_list != ["*"]:
        # Probes and Prometheus reach the API by container name / loopback, which must keep working.
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[*settings.allowed_host_list, "localhost", "127.0.0.1", "api"],
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def observe_requests(request: Request, call_next):
        """Request id, per-route latency/count metrics and one structured log line
        per request. Metrics are labelled by route *template*, never the raw URL."""
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            elapsed = time.perf_counter() - started
            template = route_template(request.scope)
            http_metrics.HTTP_REQUESTS.labels(request.method, template, str(status_code)).inc()
            http_metrics.HTTP_DURATION.labels(request.method, template).observe(elapsed)
            if template not in ("/health", "/health/live", "/health/ready", "/metrics"):
                log_event(
                    logger,
                    "http_request",
                    method=request.method,
                    route=template,
                    status=status_code,
                    duration_ms=round(elapsed * 1000, 1),
                    user_id=getattr(request.state, "user_id", None),
                    level=logging.WARNING if status_code >= 500 else logging.INFO,
                )
            request_id_var.reset(token)

    @app.exception_handler(PoolTimeoutError)
    async def pool_exhausted_handler(request: Request, exc: PoolTimeoutError) -> JSONResponse:
        """Every database connection is busy and the wait ran out: shed load with a retryable 503
        rather than a generic 500, and say so in the log (this is the signal to scale or tune the pool)."""
        metrics.count("db_pool_exhausted_total")
        logger.error("Database connection pool exhausted for %s %s", request.method, request.url.path)
        return JSONResponse(status_code=503, content={"detail": "Service busy, please retry"}, headers={"Retry-After": "2"})

    def _unavailable(request: Request, exc: Exception) -> JSONResponse:
        metrics.count("db_unavailable_total")
        logger.error("Dependency unavailable during %s %s: %s", request.method, request.url.path, type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"}, headers={"Retry-After": "5"})

    # Connection-level failures reach us unwrapped (a stopped database container is a ConnectionRefusedError or a DNS
    # failure from the driver, not a SQLAlchemy DBAPIError): they are an outage to wait out, not a bug -> 503, not 500.
    for _exc_type in (
        ConnectionError,
        socket.gaierror,
        asyncpg.exceptions.PostgresConnectionError,
        asyncpg.exceptions.CannotConnectNowError,
        asyncpg.exceptions.TooManyConnectionsError,
        redis_exceptions.ConnectionError,
        redis_exceptions.TimeoutError,
    ):
        app.add_exception_handler(_exc_type, lambda request, exc: _unavailable(request, exc))

    @app.exception_handler(DBAPIError)
    async def database_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
        if exc.connection_invalidated or isinstance(exc.orig, (ConnectionError, OSError)) or _is_transient_sqlstate(exc):
            return _unavailable(request, exc)
        logger.exception("Database error while processing %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error while processing %s %s", request.method, request.url)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(websocket_router, prefix="/ws")

    @app.get("/health/live", tags=["health"])
    async def health_live() -> JSONResponse:
        """Liveness: is this process running and able to answer? Deliberately touches no dependency -- an
        unreachable database must make the API *unready* (taken out of rotation), never *dead* (restarted)."""
        return JSONResponse(content={"status": "alive"})

    @app.get("/health/ready", tags=["health"])
    async def health_ready(
        redis: Annotated[RedisService, Depends(get_redis_service)], db: Annotated[AsyncSession, Depends(get_db)]
    ) -> JSONResponse:
        """Readiness: can this instance serve traffic right now? Requires the database and Redis -- the two
        things every request path depends on. The football provider is reported but not required: when it
        is down the API still serves everything already stored (with stale-data indicators)."""
        database_ok, redis_ok = await asyncio.gather(_database_healthy(db), _redis_healthy(redis))
        ready = database_ok and redis_ok
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "not_ready",
                "dependencies": {
                    "database": "ok" if database_ok else "unavailable",
                    "redis": "ok" if redis_ok else "unavailable",
                    "provider": "ok" if _provider_configured() else "unavailable",
                },
            },
        )

    @app.get("/version", tags=["health"])
    async def version() -> dict[str, str]:
        """What is running -- for deploy verification, support and release notes. No secrets."""
        return {"version": settings.app_version, "git_sha": settings.git_sha or "unknown", "environment": settings.environment}

    @app.get("/health", tags=["health"])
    async def health(
        redis: Annotated[RedisService, Depends(get_redis_service)], db: Annotated[AsyncSession, Depends(get_db)]
    ) -> JSONResponse:
        """Reports each critical dependency independently (Phase 2 §28)
        instead of a single always-ok status -- a degraded dependency
        surfaces as a 503 with the specific thing that's down, not a
        false-positive 200."""
        database_ok = await _database_healthy(db)
        redis_ok = await _redis_healthy(redis)
        provider_ok = _provider_configured()
        overall_ok = database_ok and redis_ok and provider_ok

        return JSONResponse(
            status_code=200 if overall_ok else 503,
            content={
                "status": "ok" if overall_ok else "degraded",
                "dependencies": {
                    "api": "ok",
                    "database": "ok" if database_ok else "unavailable",
                    "redis": "ok" if redis_ok else "unavailable",
                    "provider": "ok" if provider_ok else "unavailable",
                },
            },
        )

    async def refresh_state_gauges(db: AsyncSession, redis: RedisService) -> None:
        """Point-in-time gauges, recomputed per scrape: what is running, what is reachable, how stale live data
        is. Each probe is independent and best-effort -- a failing probe sets its gauge to 0 rather than failing
        the scrape, because "the dependency is down" is exactly what these exist to report."""
        from sqlalchemy import func, select

        from app.db.session import engine
        from app.models.enums import MatchStatus
        from app.models.match import Match
        from app.models.operations import FailedJob
        from app.websocket.manager import manager as ws_manager

        http_metrics.BUILD_INFO.labels(settings.app_version, settings.git_sha or "unknown", settings.environment).set(1)
        database_ok = await _database_healthy(db)
        redis_ok = await _redis_healthy(redis)
        http_metrics.DEPENDENCY_UP.labels("database").set(1 if database_ok else 0)
        http_metrics.DEPENDENCY_UP.labels("redis").set(1 if redis_ok else 0)
        http_metrics.DEPENDENCY_UP.labels("provider_configured").set(1 if _provider_configured() else 0)
        http_metrics.WS_PER_PROCESS.set(ws_manager.connection_count())
        pool = engine.pool
        for state, reader in (("size", "size"), ("checked_out", "checkedout"), ("overflow", "overflow")):
            if hasattr(pool, reader):
                http_metrics.DB_POOL.labels(state).set(getattr(pool, reader)())
        if not database_ok:
            return
        try:
            http_metrics.FAILED_JOBS.set(await db.scalar(select(func.count()).select_from(FailedJob).where(FailedJob.resolved_at.is_(None))) or 0)
            oldest = await db.scalar(
                select(func.min(Match.last_synced_at)).where(Match.status.in_([MatchStatus.LIVE, MatchStatus.HALFTIME]))
            )
            live = await db.scalar(select(func.count()).select_from(Match).where(Match.status.in_([MatchStatus.LIVE, MatchStatus.HALFTIME]))) or 0
            if live and oldest is None:
                http_metrics.LIVE_DATA_AGE.set(86400)  # live matches that have never synced
            elif live:
                from datetime import datetime, timezone

                http_metrics.LIVE_DATA_AGE.set(max((datetime.now(timezone.utc) - oldest).total_seconds(), 0))
            else:
                http_metrics.LIVE_DATA_AGE.set(0)
        except Exception:
            logger.warning("State gauges partially unavailable", exc_info=True)

    @app.get("/metrics", tags=["observability"])
    async def metrics_endpoint(
        redis: Annotated[RedisService, Depends(get_redis_service)], db: Annotated[AsyncSession, Depends(get_db)]
    ) -> PlainTextResponse:
        """Metrics (Phase 2 §27, cross-process since Phase 5): the API,
        worker and scheduler all push their counters to Redis, and this renders
        them together, one series per `role` label. If Redis can't be read it
        falls back to this process's own counters, as before."""
        try:
            await refresh_state_gauges(db, redis)
        except Exception:
            logger.warning("Could not refresh state gauges", exc_info=True)
        try:
            from app.services.metrics import metrics as app_metrics
            from app.services.metrics_aggregation import read_aggregate_async, render_prometheus

            await asyncio.to_thread(app_metrics.flush)  # make this process's latest numbers visible first (off the event loop)
            counters, gauges = await read_aggregate_async(redis.raw)
            if counters or gauges:
                try:
                    http_metrics.CELERY_QUEUE_LENGTH.labels("football").set(await redis.raw.llen("football"))
                except Exception:
                    pass
                body = render_prometheus(counters, gauges) + http_metrics.render().decode()
                return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")
        except Exception:
            logger.warning("Aggregated metrics unavailable; reporting this process only", exc_info=True)
        try:
            from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

            return PlainTextResponse(generate_latest() + http_metrics.render(), media_type=CONTENT_TYPE_LATEST)
        except ImportError:
            from app.services.metrics import metrics as app_metrics

            return PlainTextResponse(
                "\n".join(f"{k} {v}" for k, v in app_metrics.snapshot().items()),
                media_type="text/plain",
            )

    return app


app = create_app()
