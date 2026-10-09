from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application configuration.

    All values have safe local-dev defaults so the app can boot without a
    `.env` file; real deployments must override via environment variables.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "development" | "test" | "staging" | "production". Staging and production are "deployed": they get
    # the startup configuration checks (app/core/production_checks.py) and secure cookies.
    environment: str = "development"
    # Release identification (Phase 7), exposed by GET /version. CI stamps APP_VERSION / GIT_SHA at build time.
    app_version: str = "2.1.0"
    git_sha: str = ""
    database_url: str = (
        "postgresql+asyncpg://football:football@localhost:5432/football_livescore"
    )
    # SQLAlchemy connection pool (Phase 7). Per process: the API and each Celery worker process own one pool,
    # so total connections ~ (pool_size + max_overflow) x (api workers + celery processes) -- keep that under
    # Postgres' max_connections (100 by default). See docs/operations/capacity.md.
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout_seconds: int = 10
    """How long a request waits for a free connection before failing fast (503) rather than queueing forever."""
    db_pool_recycle_seconds: int = 1800
    """Replace connections older than this, so a firewall/proxy idle-timeout never hands out a dead one."""
    db_statement_timeout_ms: int = 15000
    """Server-side cap on one statement (0 = off). A runaway query must not hold a connection indefinitely."""

    # Football data provider abstraction (see app/services/providers).
    football_data_provider: str = "api-football"  # "api-football" | "real" (football-data.org)
    football_api_base_url: str = ""
    football_api_key: str = ""
    # api-football only: comma separated league ids to expose (empty = Premier League, La Liga, Serie A).
    football_api_league_ids: str | None = None
    # Phase 5: paid-plan features of the real provider, comma separated from
    # {events, lineups, statistics}. Empty = free tier (none of them).
    football_api_features: str = ""

    cors_origins: str = "http://localhost:3000"
    # Comma separated Host values the API answers to ("*" = any). Production must list its own hostnames,
    # which blocks Host-header attacks (poisoned links, cache poisoning). Health probes on the private
    # network use "localhost" / the container name, so those are always allowed.
    allowed_hosts: str = "*"
    # Requests with a larger declared body are refused with 413 before being read (uploads have their own cap).
    max_request_body_bytes: int = 1_048_576

    # -- Redis (Phase 2: cache-aside + pub/sub messaging) -------------------
    redis_url: str = "redis://localhost:6379/0"

    # -- Adaptive live-match polling (Phase 2 §9) ----------------------------
    # How often the worker re-syncs a match that is currently LIVE/HALFTIME.
    live_poll_interval_seconds: int = 30
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
    # Change-detection snapshot per match; refreshed on every sync, so it only lapses for matches nobody tracks.
    match_state_ttl_seconds: int = 3 * 24 * 3600

    # -- WebSockets -----------------------------------------------------------
    websocket_heartbeat_seconds: int = 30
    # Hard cap on concurrent WebSocket connections per API process, to
    # protect against uncontrolled/abusive subscription growth (§29).
    websocket_max_connections: int = 1000
    # A client that cannot accept a message within this long is disconnected (it reconnects and resyncs)
    # instead of stalling delivery to everyone else.
    websocket_send_timeout_seconds: float = 5.0
    # One client address may hold at most this many sockets (a web tab and a mobile app need 1-3; 0 = unlimited).
    websocket_max_connections_per_ip: int = 25

    # -- Celery reliability (Phase 7) ------------------------------------------------------------------
    # Periodic jobs take 0.01-2 s on a 440 k-comment database and provider syncs under a minute, so 5 minutes is generous.
    # The limit also sets how long a task from a hard-killed worker stays 'unacked' before Redis redelivers it (limit + 60 s).
    celery_task_soft_time_limit_seconds: int = 240
    celery_task_time_limit_seconds: int = 300

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

    # -- Email (Phase 7): password-reset delivery. Empty host = email is not sent (and a deployed instance
    # cannot complete a password reset -- docs/production-launch-checklist.md).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "LivePitch <no-reply@example.com>"
    smtp_starttls: bool = True
    smtp_ssl: bool = False  # implicit TLS (port 465) instead of STARTTLS
    # The web app's public origin: the base of links sent in emails.
    public_site_url: str = "http://localhost:3000"

    # -- Push notifications (Phase 3 §17/§18/§19) -- Web Push (VAPID). Empty
    # by default: web push registration is skipped (not an error) until a
    # real keypair is configured -- generate one locally, never commit it.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    # -- Discovery: content, search, trending, personalisation ---------------
    # Comma separated hostnames article images may come from. Empty = any
    # http(s) host (images are only ever *linked*, never fetched server-side).
    article_image_allowed_hosts: str = ""
    # Public article lists/details and the discovery home are cached in Redis;
    # any content change bumps a version that invalidates all of them at once.
    article_cache_ttl_seconds: int = 120
    discovery_cache_ttl_seconds: int = 120
    # Trending: results are precomputed by a beat task and read from Redis.
    trending_cache_ttl_seconds: int = 900
    trending_window_hours: int = 24
    trending_half_life_hours: float = 6.0
    # The personalised feed is cached per user for a short time.
    feed_cache_ttl_seconds: int = 45
    # View de-duplication: the same viewer re-opening the same thing within
    # this window counts once (refresh-spam protection).
    view_dedup_seconds: int = 1800
    # Rate limits (per client IP, per minute).
    search_rate_limit_per_minute: int = 60
    track_rate_limit_per_minute: int = 120
    # Unified search results are public and identical for everyone, so they are cached briefly per normalised
    # query. Kept at the live-data TTL because results can include match scores. (Measured: a search costs about ten
    # times a cached read in CPU, and it was the first endpoint to saturate under load.)
    search_results_cache_ttl_seconds: int = 30
    # Searches that match nothing stored may ask the football provider (all clients together, per minute).
    search_provider_fallbacks_per_minute: int = 10
    # Conservative content notifications: at most this many article pushes per
    # user per UTC day, however many articles match.
    content_notification_daily_cap: int = 3
    # A free-text query is only shown as "popular" once this many different
    # viewers selected a result after searching it (keeps one person's private
    # phrase out of a public list).
    popular_search_min_viewers: int = 3

    # Comma separated CIDR ranges of reverse proxies / the web app's server whose
    # `X-Forwarded-For` header is believed (so per-client rate limits see the
    # real visitor, not the proxy). Empty = never trust it. The header is
    # ignored for any other peer, so it cannot be spoofed to dodge a limit.
    trusted_proxy_cidrs: str = ""

    # -- Media (Phase 6) ---------------------------------------------------------
    # Where uploaded images live: "local" (a directory, fine for dev/single node)
    # or "s3" (Amazon S3, Cloudflare R2 or MinIO -- anything S3-compatible).
    media_storage_backend: str = "local"
    media_local_root: str = "./media-data"
    s3_bucket: str = "livepitch-media"
    s3_endpoint_url: str = ""  # MinIO: http://minio:9000 ; R2: https://<account>.r2.cloudflarestorage.com
    s3_region: str = "us-east-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    # If set, media URLs point straight at this origin (a CDN, or a public
    # bucket) instead of being streamed through the API.
    media_public_base_url: str = ""
    # Absolute origin of this API as clients see it -- used to build media URLs.
    public_api_url: str = "http://localhost:8000"
    media_max_bytes: int = 5 * 1024 * 1024
    media_min_side: int = 64
    media_max_side: int = 8000
    media_max_pixels: int = 40_000_000
    media_uploads_per_minute: int = 20
    media_uploads_per_day: int = 200

    # -- Community (Phase 6) --------------------------------------------------------
    comment_max_length: int = 2000
    comment_max_links: int = 2
    comments_per_minute: int = 5
    comments_per_hour: int = 40
    # Independent reports needed to hide a comment pending moderator review.
    comment_auto_hide_reports: int = 3
    reactions_per_minute: int = 30
    poll_votes_per_minute: int = 20
    comment_cache_ttl_seconds: int = 30
    poll_cache_ttl_seconds: int = 30

    # -- Analytics / predictions (Phase 6b) -----------------------------------------------
    analytics_cache_ttl_seconds: int = 900
    analytics_per_minute: int = 240
    """Per-IP ceiling on the analytics/comparison endpoints (each distinct team/match is an uncached aggregate on first request)."""
    prediction_cache_ttl_seconds: int = 300
    analytics_window_matches: int = 20
    """How many recent finished matches per team feed the analytics and the model."""
    prediction_horizon_hours: int = 72
    """Predictions are generated for matches kicking off within this window."""

    # -- Billing / monetisation (Phase 6b) -----------------------------------------------
    billing_provider: str = "test"  # "test" | "stripe"
    billing_webhook_secret: str = "dev-only-webhook-secret"
    billing_webhook_tolerance_seconds: int = 300
    billing_grace_days: int = 3
    billing_success_url: str = "http://localhost:3000/premium?checkout=success"
    billing_cancel_url: str = "http://localhost:3000/premium?checkout=cancelled"
    stripe_secret_key: str = ""
    checkout_per_hour: int = 10
    profile_reports_per_hour: int = 10
    webhook_per_minute: int = 120
    ads_enabled: bool = False

    # -- Logging (Phase 6) -------------------------------------------------------------
    log_format: str = "json"  # "json" | "text"
    log_level: str = "INFO"
    service_name: str = "api"


    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def is_deployed(self) -> bool:
        """Staging and production: real users or real data, so secure defaults are not optional."""
        return self.environment.lower() in ("staging", "production")

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()] or ["*"]

    @property
    def media_host_list(self) -> list[str]:
        return [h.strip().lower() for h in self.article_image_allowed_hosts.split(",") if h.strip()]

    @property
    def article_image_host_list(self) -> list[str]:
        return [h.strip().lower() for h in self.article_image_allowed_hosts.split(",") if h.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
