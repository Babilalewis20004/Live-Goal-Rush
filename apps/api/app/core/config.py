from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application configuration.

    All values have safe local-dev defaults so the app can boot without a
    `.env` file; real deployments must override via environment variables.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = (
        "postgresql+asyncpg://football:football@localhost:5432/football_livescore"
    )

    # Football data provider abstraction (see app/services/providers).
    football_data_provider: str = "mock"  # "mock" | "real"
    football_api_base_url: str = ""
    football_api_key: str = ""

    cors_origins: str = "http://localhost:3000"

    # -- Redis (Phase 2: cache-aside + pub/sub messaging) -------------------
    redis_url: str = "redis://localhost:6379/0"

    # -- Adaptive live-match polling (Phase 2 §9) ----------------------------
    # How often the worker re-syncs a match that is currently LIVE/HALFTIME.
    live_poll_interval_seconds: int = 15
    # How often a match within the "kickoff approaching" window (< 15 min
    # out) is re-checked, in case it has gone live.
    upcoming_poll_interval_seconds: int = 60
    # How often a recently-finished match is re-synced, to catch any
    # provider corrections that arrive shortly after full time.
    post_match_sync_interval_seconds: int = 60

    # -- Cache TTLs (Phase 2 §4, documented in docs/architecture/caching.md) -
    # Live match/detail/event data: short-lived, matches the live poll
    # interval so a cache entry never meaningfully outlives its sync cycle.
    redis_live_match_ttl_seconds: int = 30
    # Slower-moving data (today/upcoming fixtures, standings, team
    # fixtures): refreshed by the background sync jobs, not by request
    # traffic, so a longer TTL is safe.
    redis_default_ttl_seconds: int = 300

    # -- WebSockets -----------------------------------------------------------
    websocket_heartbeat_seconds: int = 30
    # Hard cap on concurrent WebSocket connections per API process, to
    # protect against uncontrolled/abusive subscription growth (§29).
    websocket_max_connections: int = 1000

    # -- Provider sync retry/backoff (§10) -------------------------------------
    sync_max_retries: int = 3
    sync_backoff_seconds: int = 5

    # -- Mock provider live-match time simulation ------------------------------
    # The bundled mock provider has no real upstream to change over time, so
    # Phase 2 makes its "live" fixtures progress deterministically from the
    # API process's start time: every N real seconds, the simulated match
    # clock advances one minute, revealing events (and the score computed
    # from them) as it passes each event's minute. This is what makes the
    # real-time pipeline observable end-to-end with FOOTBALL_DATA_PROVIDER=mock
    # (the default) without a special "simulate a goal" trigger endpoint.
    # Not used by the real provider.
    mock_live_seconds_per_minute: float = 2.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
