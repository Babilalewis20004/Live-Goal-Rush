"""Startup configuration validation (Phase 7).

Every setting has a convenient local-development default, which is exactly what makes a mis-deployed
instance dangerous: a forgotten `JWT_SECRET` silently means anyone can mint tokens, a forgotten
`BILLING_WEBHOOK_SECRET` means anyone can grant themselves Premium. When `ENVIRONMENT` is `staging` or
`production` the API (and the Celery processes, which import the same app) therefore refuse to start
while any *error* below holds, and log every *warning*.

`problems(settings)` is a pure function of the settings object so each rule is unit-tested.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.core.config import Settings

logger = logging.getLogger(__name__)

_DEV_JWT_SECRET_MARKER = "dev-insecure"
_DEV_WEBHOOK_SECRET = "dev-only-webhook-secret"
_KNOWN_WEAK_PASSWORDS = {"football", "postgres", "password", "admin", "livepitch-secret", "changeme", "secret"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}  # nosec B104 - hosts that mean "this machine", not a bind


class ConfigurationError(RuntimeError):
    """Raised at startup when a deployed environment is configured unsafely."""


@dataclass
class Findings:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _password(url: str) -> str:
    return urlparse(url).password or ""


def _looks_random(secret: str) -> bool:
    return len(set(secret)) >= 10


def problems(s: Settings) -> Findings:
    """Everything wrong with `s` for the environment it declares. Development and test: nothing is required."""
    out = Findings()
    if not s.is_deployed:
        return out
    prod = s.is_production

    def error(message: str) -> None:
        out.errors.append(message)

    def strict(message: str) -> None:
        """An error in production, a warning in staging (which legitimately uses test-mode credentials)."""
        (out.errors if prod else out.warnings).append(message)

    # -- secrets -------------------------------------------------------------------------------------
    if _DEV_JWT_SECRET_MARKER in s.jwt_secret or len(s.jwt_secret) < 32 or not _looks_random(s.jwt_secret):
        error("JWT_SECRET must be a random value of at least 32 characters (it is unset, short, or the development default)")
    if s.jwt_algorithm.upper() not in ("HS256", "HS384", "HS512"):
        error(f"JWT_ALGORITHM {s.jwt_algorithm!r} is not an allowed HMAC algorithm")

    # -- data stores ---------------------------------------------------------------------------------
    if _host(s.database_url) in _LOCAL_HOSTS and prod:
        out.warnings.append("DATABASE_URL points at localhost; expected a database service/host in production")
    if _password(s.database_url).lower() in _KNOWN_WEAK_PASSWORDS or not _password(s.database_url):
        error("DATABASE_URL has an empty or well-known password")
    if not _password(s.redis_url) and not s.redis_url.startswith("rediss://"):
        strict("REDIS_URL has no password and is not TLS (rediss://); Redis holds the job queue and rate-limit state")

    # -- network exposure ----------------------------------------------------------------------------
    origins = s.cors_origin_list
    if not origins or "*" in origins:
        error("CORS_ORIGINS must list the exact web origins (no '*', not empty)")
    for origin in origins:
        if origin == "*":
            continue
        if _host(origin) in _LOCAL_HOSTS:
            strict(f"CORS_ORIGINS includes a local origin ({origin})")
        elif not origin.startswith("https://"):
            strict(f"CORS_ORIGINS origin {origin} is not https")
    if s.allowed_host_list == ["*"]:
        strict("ALLOWED_HOSTS is '*'; list the public hostnames to reject forged Host headers")
    if not s.public_api_url.startswith("https://"):
        strict("PUBLIC_API_URL is not https (media links and callbacks are built from it)")
    for name, url in (("BILLING_SUCCESS_URL", s.billing_success_url), ("BILLING_CANCEL_URL", s.billing_cancel_url)):
        if _host(url) in _LOCAL_HOSTS or not url.startswith("https://"):
            strict(f"{name} is not a public https URL")
    if not s.trusted_proxy_cidrs.strip():
        strict("TRUSTED_PROXY_CIDRS is empty: every client behind the reverse proxy shares one rate-limit bucket")

    # -- football data provider --------------------------------------------------------------------
    if not s.football_api_key.strip():
        error("FOOTBALL_API_KEY is not set; live data cannot be fetched")

    # -- payments ------------------------------------------------------------------------------------
    provider = s.billing_provider.lower()
    if provider == "test":
        strict("BILLING_PROVIDER=test accepts self-signed webhooks and must not run in production")
    elif provider == "stripe":
        if not s.stripe_secret_key.strip():
            error("STRIPE_SECRET_KEY is not set")
    else:
        error(f"BILLING_PROVIDER {s.billing_provider!r} is unknown")
    if s.billing_webhook_secret == _DEV_WEBHOOK_SECRET or len(s.billing_webhook_secret) < 16:
        error("BILLING_WEBHOOK_SECRET must be a long random value (a forgeable webhook grants Premium to anyone)")

    # -- media ---------------------------------------------------------------------------------------
    if s.media_storage_backend.lower() == "s3":
        if not s.s3_access_key or not s.s3_secret_key:
            error("MEDIA_STORAGE_BACKEND=s3 but S3_ACCESS_KEY / S3_SECRET_KEY are not set")
        elif s.s3_secret_key.lower() in _KNOWN_WEAK_PASSWORDS:
            error("S3_SECRET_KEY is a well-known development value")
    else:
        out.warnings.append("MEDIA_STORAGE_BACKEND is 'local': uploads are not shared between instances and are lost with the container")

    # -- softer guidance ----------------------------------------------------------------------------
    if s.access_token_expire_minutes > 60:
        out.warnings.append("ACCESS_TOKEN_EXPIRE_MINUTES is over an hour; access tokens cannot be revoked before they expire")
    if not s.smtp_host:
        out.warnings.append("SMTP_HOST is not set: password-reset emails cannot be delivered, so users cannot recover accounts")
    if not s.vapid_public_key or not s.vapid_private_key:
        out.warnings.append("VAPID keys are not set: web push notifications are disabled")
    if s.log_format.lower() != "json":
        out.warnings.append("LOG_FORMAT is not json; log pipelines expect one JSON object per line")
    if s.db_pool_size + s.db_max_overflow < 1:
        error("DB_POOL_SIZE + DB_MAX_OVERFLOW must be at least 1")
    return out


def enforce(s: Settings) -> Findings:
    """Log the warnings and raise `ConfigurationError` listing every error. Called once at import of `app.main`."""
    findings = problems(s)
    for warning in findings.warnings:
        logger.warning("configuration warning (%s): %s", s.environment, warning)
    if findings.errors:
        listing = "\n  - ".join(findings.errors)
        raise ConfigurationError(
            f"Refusing to start with ENVIRONMENT={s.environment}: unsafe configuration:\n  - {listing}\n"
            "Fix the environment variables above (see .env.production.example)."
        )
    return findings
