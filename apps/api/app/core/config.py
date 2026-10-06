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
    # Phase 5: paid-plan features of the real provider, comma separated from
    # {events, lineups, statistics}. Empty = free tier (none of them).
    football_api_features: str = ""

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
    # Phase 4: data that effectively never changes once written -- a
    # finished match's lineups/statistics, squads, player profiles, and
    # match-context form/head-to-head (which only look at results from
    # before that match).
    redis_static_ttl_seconds: int = 3600

    # -- WebSockets -----------------------------------------------------------
    websocket_heartbeat_seconds: int = 30
    # Hard cap on concurrent WebSocket connections per API process, to
    # protect against uncontrolled/abusive subscription growth (§29).
    websocket_max_connections: int = 1000

    # -- Provider sync retry/backoff (§10) -------------------------------------
    sync_max_retries: int = 3
    # Phase 4: ceiling on on-demand syncs that unauthenticated *reads* may queue
    # (empty squads, unenriched players) across all entities per minute, so
    # walking ids can't turn the public API into a provider-quota drain.
    sync_request_budget_per_minute: int = 20
    sync_backoff_seconds: int = 5

    # -- Auth (Phase 3) ---------------------------------------------------------
    # Safe local-dev default so the app still boots without a `.env` --
    # every real deployment MUST override this via the environment.
    jwt_secret: str = "dev-insecure-secret-change-me-before-deploying-anywhere-real"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    password_reset_token_expire_minutes: int = 30

    # -- Rate limiting (Phase 3) -- Redis fixed-window counters (§21) ----------
    rate_limit_register_per_hour: int = 5
    rate_limit_login_per_minute: int = 10
    rate_limit_password_reset_per_hour: int = 5

    # -- Push notifications (Phase 3 §17/§18/§19) -- Web Push (VAPID). Empty
    # by default: web push registration is skipped (not an error) until a
    # real keypair is configured -- generate one locally, never commit it.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

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
