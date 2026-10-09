"""Startup configuration validation (Phase 7 §5)."""

import pytest

from app.core.config import Settings
from app.core.production_checks import ConfigurationError, enforce, problems

STRONG_JWT = "k3Jd9sLq2VxPz7RbN4mWc8TfHy6AeUgo1ZiXv5QtYrE0"


def production(**overrides) -> Settings:
    """A fully valid production configuration; each test breaks exactly one thing."""
    base = dict(
        environment="production",
        jwt_secret=STRONG_JWT,
        database_url="postgresql+asyncpg://app:Zq81pLmN4vB7xK2c@db.internal:5432/football",
        redis_url="redis://:Rk29xTq7LpWm3Vn8@redis.internal:6379/0",
        cors_origins="https://livepitch.example",
        allowed_hosts="livepitch.example",
        public_api_url="https://livepitch.example",
        billing_success_url="https://livepitch.example/premium?checkout=success",
        billing_cancel_url="https://livepitch.example/premium?checkout=cancelled",
        trusted_proxy_cidrs="172.16.0.0/12",
        football_api_key="provider-key-123",
        billing_provider="stripe",
        stripe_secret_key="sk_live_example_key_value",
        billing_webhook_secret="whsec_9fQ2pLx7TzK4mVb8NcR1",
        media_storage_backend="s3",
        s3_access_key="AKIAEXAMPLE",
        s3_secret_key="s3-very-secret-value-123",
        vapid_public_key="pub",
        vapid_private_key="priv",
        smtp_host="smtp.example.com",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def errors(**overrides) -> list[str]:
    return problems(production(**overrides)).errors


def test_a_complete_production_configuration_passes_without_errors():
    findings = problems(production())
    assert findings.errors == []
    assert findings.warnings == []


@pytest.mark.parametrize("environment", ["development", "test"])
def test_local_environments_are_never_blocked(environment):
    findings = problems(Settings(_env_file=None, environment=environment))  # all defaults, insecure on purpose
    assert findings.errors == [] and findings.warnings == []


@pytest.mark.parametrize(
    "secret",
    ["dev-insecure-secret-change-me-before-deploying-anywhere-real", "short", "a" * 40, ""],
)
def test_weak_or_default_jwt_secrets_are_refused(secret):
    assert any("JWT_SECRET" in e for e in errors(jwt_secret=secret))


def test_the_none_algorithm_is_refused():
    assert any("JWT_ALGORITHM" in e for e in errors(jwt_algorithm="none"))


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://football:football@db:5432/x",
        "postgresql+asyncpg://postgres:postgres@db:5432/x",
        "postgresql+asyncpg://app@db:5432/x",  # no password at all
    ],
)
def test_default_or_missing_database_passwords_are_refused(url):
    assert any("DATABASE_URL" in e for e in errors(database_url=url))


def test_redis_without_a_password_is_an_error_in_production_but_a_warning_in_staging():
    assert any("REDIS_URL" in e for e in errors(redis_url="redis://redis:6379/0"))
    staging = problems(production(environment="staging", redis_url="redis://redis:6379/0"))
    assert not any("REDIS_URL" in e for e in staging.errors)
    assert any("REDIS_URL" in w for w in staging.warnings)


def test_tls_redis_without_a_password_is_acceptable():
    assert not any("REDIS_URL" in e for e in errors(redis_url="rediss://redis.internal:6380/0"))


@pytest.mark.parametrize("origins", ["*", "", "https://a.example,*"])
def test_wildcard_or_empty_cors_is_refused(origins):
    assert any("CORS_ORIGINS" in e for e in errors(cors_origins=origins))


def test_production_cors_must_be_https_and_not_local():
    assert any("CORS_ORIGINS" in e for e in errors(cors_origins="http://livepitch.example"))
    assert any("CORS_ORIGINS" in e for e in errors(cors_origins="https://livepitch.example,http://localhost:3000"))


def test_production_requires_explicit_allowed_hosts_and_a_trusted_proxy():
    assert any("ALLOWED_HOSTS" in e for e in errors(allowed_hosts="*"))
    assert any("TRUSTED_PROXY_CIDRS" in e for e in errors(trusted_proxy_cidrs=""))


def test_public_urls_must_be_https():
    assert any("PUBLIC_API_URL" in e for e in errors(public_api_url="http://livepitch.example"))
    assert any("BILLING_SUCCESS_URL" in e for e in errors(billing_success_url="http://localhost:3000/x"))


def test_a_missing_provider_key_is_refused():
    assert any("FOOTBALL_API_KEY" in e for e in errors(football_api_key="  "))


def test_the_test_billing_provider_is_refused_in_production_only():
    assert any("BILLING_PROVIDER=test" in e for e in errors(billing_provider="test"))
    staging = problems(production(environment="staging", billing_provider="test"))
    assert not any("BILLING_PROVIDER=test" in e for e in staging.errors)
    assert any("BILLING_PROVIDER=test" in w for w in staging.warnings)


def test_stripe_needs_its_secret_and_a_real_webhook_secret():
    assert any("STRIPE_SECRET_KEY" in e for e in errors(stripe_secret_key=""))
    assert any("BILLING_WEBHOOK_SECRET" in e for e in errors(billing_webhook_secret="dev-only-webhook-secret"))
    assert any("BILLING_WEBHOOK_SECRET" in e for e in errors(billing_webhook_secret="short"))


def test_s3_credentials_are_required_and_must_not_be_the_dev_defaults():
    assert any("S3_" in e for e in errors(s3_access_key="", s3_secret_key=""))
    assert any("S3_SECRET_KEY" in e for e in errors(s3_secret_key="livepitch-secret"))


def test_staging_is_checked_for_secrets_too():
    staging = problems(production(environment="staging", jwt_secret="short"))
    assert any("JWT_SECRET" in e for e in staging.errors)


def test_enforce_raises_listing_every_problem_at_once():
    with pytest.raises(ConfigurationError) as raised:
        enforce(production(jwt_secret="short", cors_origins="*", football_api_key=""))
    message = str(raised.value)
    assert "JWT_SECRET" in message and "CORS_ORIGINS" in message and "FOOTBALL_API_KEY" in message
    assert "ENVIRONMENT=production" in message


def test_a_missing_mail_server_is_called_out_because_password_reset_needs_it():
    findings = problems(production(smtp_host=""))
    assert findings.errors == []
    assert any("SMTP_HOST" in w for w in findings.warnings)


def test_enforce_returns_warnings_without_raising(caplog):
    with caplog.at_level("WARNING"):
        findings = enforce(production(vapid_public_key="", media_storage_backend="local"))
    assert findings.errors == []
    assert any("VAPID" in w for w in findings.warnings)
    assert any("configuration warning" in r.message for r in caplog.records)


def test_the_application_refuses_to_start_unsafely_configured(monkeypatch):
    from app.core.config import settings
    from app.main import create_app

    monkeypatch.setattr(settings, "environment", "production")  # everything else is the insecure dev default
    with pytest.raises(ConfigurationError):
        create_app()
