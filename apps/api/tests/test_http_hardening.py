"""Security headers, request-size limits, trusted hosts, health probes, version (Phase 7 §22/§24/§33/§40)."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.main import create_app


async def test_every_response_carries_the_security_headers(client):
    resp = await client.get("/api/v1/capabilities")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]
    assert "permissions-policy" in resp.headers
    assert "strict-transport-security" not in resp.headers  # development: no HSTS


async def test_hsts_is_sent_when_deployed(monkeypatch, fake_redis, test_engine):
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr("app.main.enforce_configuration", lambda _s: None)  # config validity is tested elsewhere
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health/live")
    assert "max-age=" in resp.headers["strict-transport-security"]


@pytest.mark.parametrize("path", ["/api/v1/users/me", "/api/v1/auth/refresh", "/api/v1/subscription"])
async def test_credential_bearing_responses_are_never_cacheable(client, path):
    resp = await client.request("GET" if path != "/api/v1/auth/refresh" else "POST", path, json={} if "refresh" in path else None)
    assert resp.headers["cache-control"] == "no-store"


async def test_api_docs_are_available_in_development_but_not_when_deployed(client, monkeypatch):
    assert (await client.get("/openapi.json")).status_code == 200
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr("app.main.enforce_configuration", lambda _s: None)
    deployed = create_app()
    async with AsyncClient(transport=ASGITransport(app=deployed), base_url="http://test") as ac:
        assert (await ac.get("/openapi.json")).status_code == 404
        assert (await ac.get("/docs")).status_code == 404


# -- request size ---------------------------------------------------------------------------------


async def test_oversized_json_bodies_are_refused_before_processing(client):
    body = b'{"email":"' + b"a" * (settings.max_request_body_bytes + 10) + b'"}'
    resp = await client.post("/api/v1/auth/login", content=body, headers={"content-type": "application/json"})
    assert resp.status_code == 413


async def test_a_chunked_body_without_content_length_is_also_capped(client):
    async def chunks():
        for _ in range(3):
            yield b"x" * (settings.max_request_body_bytes // 2)

    resp = await client.post("/api/v1/auth/login", content=chunks(), headers={"content-type": "application/json"})
    assert resp.status_code == 413


async def test_normal_sized_requests_are_unaffected(client):
    resp = await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert resp.status_code == 401


async def test_upload_routes_get_a_larger_allowance_than_json_routes(client, make_user):
    from app.models.enums import UserRole

    _ed, headers = await make_user("ed@example.com", UserRole.EDITOR)
    big = b"\x00" * (settings.max_request_body_bytes + 1024)  # over the JSON cap, under the upload cap
    resp = await client.post("/api/v1/editor/media", headers=headers, files={"file": ("x.png", big, "image/png")})
    assert resp.status_code != 413  # rejected (or not) by the image validator, not the size gate


# -- trusted hosts ----------------------------------------------------------------------------------


async def test_unknown_host_headers_are_rejected_when_allowed_hosts_is_set(monkeypatch):
    monkeypatch.setattr(settings, "allowed_hosts", "livepitch.example")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://evil.example") as ac:
        assert (await ac.get("/health/live")).status_code == 400
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://livepitch.example") as ac:
        assert (await ac.get("/health/live")).status_code == 200
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as ac:  # container probes
        assert (await ac.get("/health/live")).status_code == 200


# -- probes and version -------------------------------------------------------------------------------


async def test_liveness_touches_no_dependency(client, monkeypatch):
    async def boom(*_a, **_k):
        raise AssertionError("liveness must not call a dependency")

    monkeypatch.setattr("app.main._database_healthy", boom)
    monkeypatch.setattr("app.main._redis_healthy", boom)
    resp = await client.get("/health/live")
    assert resp.status_code == 200 and resp.json() == {"status": "alive"}


async def test_readiness_is_ok_when_database_and_redis_answer(client):
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["dependencies"]["database"] == "ok" and body["dependencies"]["redis"] == "ok"


async def test_readiness_fails_when_redis_is_down_but_liveness_still_passes(client, monkeypatch):
    async def down(_redis):
        return False

    monkeypatch.setattr("app.main._redis_healthy", down)
    ready = await client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["dependencies"]["redis"] == "unavailable"
    assert (await client.get("/health/live")).status_code == 200


async def test_readiness_fails_when_the_database_is_down(client, monkeypatch):
    async def down(_session):
        return False

    monkeypatch.setattr("app.main._database_healthy", down)
    resp = await client.get("/health/ready")
    assert resp.status_code == 503 and resp.json()["dependencies"]["database"] == "unavailable"


async def test_readiness_does_not_require_the_football_provider(client, monkeypatch):
    monkeypatch.setattr("app.main._provider_configured", lambda: False)
    resp = await client.get("/health/ready")
    assert resp.status_code == 200 and resp.json()["dependencies"]["provider"] == "unavailable"


async def test_version_reports_the_release_and_nothing_secret(client):
    resp = await client.get("/version")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == settings.app_version
    assert set(body) == {"version", "git_sha", "environment"}


async def test_health_probes_are_not_logged_per_request(client, caplog):
    with caplog.at_level("INFO"):
        await client.get("/health/live")
        await client.get("/health/ready")
    assert not [r for r in caplog.records if getattr(r, "event", None) == "http_request"]


# -- request correlation -----------------------------------------------------------------------------


async def test_a_well_formed_incoming_request_id_is_echoed_and_logged(client, caplog):
    with caplog.at_level("INFO"):
        resp = await client.get("/api/v1/capabilities", headers={"X-Request-ID": "proxy-abc123456789"})
    assert resp.headers["x-request-id"] == "proxy-abc123456789"
    assert any(getattr(r, "event", None) == "http_request" for r in caplog.records)


async def test_a_hostile_request_id_is_replaced_not_reflected(client):
    resp = await client.get("/api/v1/capabilities", headers={"X-Request-ID": "x\r\nSet-Cookie: a=b"})
    assert "set-cookie" not in resp.headers
    assert "\n" not in resp.headers["x-request-id"]


async def test_the_authenticated_user_id_appears_in_the_request_log(authenticated_client, test_user, caplog):
    with caplog.at_level("INFO"):
        await authenticated_client.get("/api/v1/users/me")
    lines = [r for r in caplog.records if getattr(r, "event", None) == "http_request"]
    assert lines and lines[-1].user_id == test_user.id
    assert "test@example.com" not in "".join(str(v) for r in lines for v in r.__dict__.values())


# -- database failure handling ----------------------------------------------------------------------------


async def test_pool_exhaustion_is_a_retryable_503_not_a_500(client, monkeypatch):
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    from app.services import football_service

    async def exhausted(*_a, **_k):
        raise PoolTimeout("QueuePool limit of size 10 overflow 10 reached")

    monkeypatch.setattr(football_service.FootballService, "get_live_matches", exhausted)
    resp = await client.get("/api/v1/matches/live")
    assert resp.status_code == 503
    assert resp.headers["retry-after"]


async def test_a_dropped_database_connection_is_a_retryable_503(client, monkeypatch):
    from sqlalchemy.exc import DBAPIError

    from app.services import football_service

    async def dropped(*_a, **_k):
        raise DBAPIError("SELECT 1", {}, ConnectionResetError("server closed the connection"), connection_invalidated=True)

    monkeypatch.setattr(football_service.FootballService, "get_live_matches", dropped)
    resp = await client.get("/api/v1/matches/live")
    assert resp.status_code == 503 and resp.headers["retry-after"]


async def test_the_connection_pool_is_bounded_and_has_a_statement_timeout():
    from app.db.session import engine

    pool = engine.pool
    assert pool.size() == settings.db_pool_size
    assert pool._max_overflow == settings.db_max_overflow
    assert pool._timeout == settings.db_pool_timeout_seconds
    assert pool._recycle == settings.db_pool_recycle_seconds
    assert pool._pre_ping is True
    assert settings.db_statement_timeout_ms > 0


async def test_a_runaway_statement_is_cancelled_by_the_server(test_engine):
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import create_async_engine

    from tests.conftest import TEST_DATABASE_URL

    engine = create_async_engine(TEST_DATABASE_URL, connect_args={"server_settings": {"statement_timeout": "200"}})
    try:
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError):
                await conn.execute(text("SELECT pg_sleep(2)"))
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError(111, "Connection refused"),
        __import__("socket").gaierror(-2, "Name or service not known"),
        ConnectionResetError("reset by peer"),
    ],
    ids=["refused", "dns", "reset"],
)
async def test_a_stopped_database_is_a_503_even_when_the_driver_raises_a_bare_connection_error(client, monkeypatch, error):
    """A stopped database container surfaces as a raw ConnectionRefusedError / DNS failure, not a SQLAlchemy error."""
    from app.services import football_service

    async def stopped(*_a, **_k):
        raise error

    monkeypatch.setattr(football_service.FootballService, "get_live_matches", stopped)
    resp = await client.get("/api/v1/matches/live")
    assert resp.status_code == 503 and resp.headers["retry-after"]
    assert resp.json() == {"detail": "Service temporarily unavailable"}  # no internals leaked


async def test_asyncpg_connection_failures_are_503_too(client, monkeypatch):
    import asyncpg

    from app.services import football_service

    async def too_many(*_a, **_k):
        raise asyncpg.exceptions.TooManyConnectionsError("sorry, too many clients already")

    monkeypatch.setattr(football_service.FootballService, "get_live_matches", too_many)
    assert (await client.get("/api/v1/matches/live")).status_code == 503


async def test_the_database_driver_gives_up_connecting_in_seconds_not_a_minute():
    from app.db.session import CONNECT_ARGS

    assert CONNECT_ARGS["timeout"] <= 10  # asyncpg's default is 60 s per connection attempt
    assert CONNECT_ARGS["command_timeout"] <= 60
    assert CONNECT_ARGS["server_settings"]["application_name"]


@pytest.mark.parametrize(
    "sqlstate,expected",
    [("57P01", 503), ("57P03", 503), ("53300", 503), ("08006", 503), ("40P01", 503), ("57014", 503), ("23505", 500), ("42P01", 500)],
)
async def test_database_errors_are_503_only_when_a_retry_could_help(client, monkeypatch, sqlstate, expected):
    """Shutting down / starting up / out of connections / deadlock: retry. A constraint or syntax error: that's our bug (500)."""
    from sqlalchemy.exc import DBAPIError

    from app.services import football_service

    class Driver(Exception):
        pass

    driver = Driver("boom")
    driver.sqlstate = sqlstate

    async def failing(*_a, **_k):
        raise DBAPIError("SELECT 1", {}, driver)

    monkeypatch.setattr(football_service.FootballService, "get_live_matches", failing)
    resp = await client.get("/api/v1/matches/live")
    assert resp.status_code == expected
    if expected == 503:
        assert resp.headers["retry-after"]
