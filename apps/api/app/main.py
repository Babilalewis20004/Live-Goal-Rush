import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from app.api.v1.router import api_router
from app.api.v1.websocket import router as websocket_router
from app.core.config import settings
from app.core.redis_client import get_redis_service
from app.db.session import AsyncSessionLocal
from app.services.providers import get_provider
from app.services.seed import seed_database
from app.websocket.manager import manager
from app.websocket.pubsub_bridge import PubSubBridge

logger = logging.getLogger(__name__)


async def _database_healthy() -> bool:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("Database health check failed", exc_info=True)
        return False


def _provider_configured() -> bool:
    """A cheap reachability signal, not a live network call on every health
    check (that would itself count against the provider's rate limit) --
    true if the configured provider constructed successfully (the mock
    provider always does; the real one requires base_url/api_key)."""
    try:
        get_provider()
        return True
    except Exception:
        logger.warning("Provider is not configured correctly", exc_info=True)
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await seed_database()
    except Exception:
        logger.exception("Startup seeding failed; continuing without a pre-warmed database")

    bridge = PubSubBridge(redis=get_redis_service(), manager=manager)
    bridge.start()
    try:
        yield
    finally:
        await bridge.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Football Livescore API",
        description="Provider-agnostic, real-time football livescore API.",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error while processing %s %s", request.method, request.url)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(websocket_router, prefix="/ws")

    @app.get("/health", tags=["health"])
    async def health() -> JSONResponse:
        """Reports each critical dependency independently (Phase 2 §28)
        instead of a single always-ok status -- a degraded dependency
        surfaces as a 503 with the specific thing that's down, not a
        false-positive 200."""
        redis = get_redis_service()
        database_ok = await _database_healthy()
        redis_ok = await redis.health_check()
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

    @app.get("/metrics", tags=["observability"])
    async def metrics_endpoint() -> PlainTextResponse:
        """Basic metrics (Phase 2 §27). Reports this process's counters --
        see app/services/metrics.py's docstring for why the worker/
        scheduler's counters aren't aggregated in here too."""
        try:
            from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

            return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
        except ImportError:
            from app.services.metrics import metrics as app_metrics

            return PlainTextResponse(
                "\n".join(f"{k} {v}" for k, v in app_metrics.snapshot().items()),
                media_type="text/plain",
            )

    return app


app = create_app()
