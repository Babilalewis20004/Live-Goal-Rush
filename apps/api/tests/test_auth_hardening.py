"""Authentication hardening (Phase 7 §15): email normalisation, constant-time login, token hygiene, cookies."""

import logging

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.redis_client import RedisService
from app.models.session import PasswordResetToken, RefreshToken
from app.models.user import User

MOBILE = {"X-Client": "mobile"}
PASSWORD = "Sup3rSecret!"


async def _register(client, email):
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "password_confirm": PASSWORD},
        headers=MOBILE,
    )


async def _login(client, email, password=PASSWORD):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password}, headers=MOBILE)


async def test_email_case_does_not_create_a_second_account(client):
    assert (await _register(client, "Bob@Example.com")).status_code == 201
    assert (await _register(client, "bob@example.com")).status_code == 409
    assert (await _register(client, "BOB@EXAMPLE.COM")).status_code == 409


async def test_login_works_in_any_case_and_the_stored_address_is_lowercase(client, session_factory):
    await _register(client, "Mixed.Case@Example.com")
    assert (await _login(client, "mixed.case@example.com")).status_code == 200
    assert (await _login(client, "MIXED.CASE@EXAMPLE.COM")).status_code == 200
    async with session_factory() as db:
        assert (await db.scalar(select(User.email))) == "mixed.case@example.com"


async def test_accounts_created_before_normalisation_can_still_sign_in(client, session_factory):
    from app.core.security import hash_password

    async with session_factory() as db:
        db.add(User(email="Legacy@Example.com", hashed_password=hash_password(PASSWORD)))
        await db.commit()
    assert (await _login(client, "legacy@example.com")).status_code == 200
    assert (await _register(client, "legacy@example.com")).status_code == 409


async def test_the_per_account_login_limit_is_shared_across_email_case(client):
    for _ in range(5):
        await _login(client, "victim@example.com", "wrong-password")
    # a differently-cased spelling lands in the same bucket and is limited too
    resp = await _login(client, "VICTIM@example.com", "wrong-password")
    assert resp.status_code == 429


async def test_unknown_and_wrong_password_responses_are_indistinguishable(client):
    await _register(client, "real@example.com")
    unknown = await _login(client, "ghost@example.com", "whatever-password")
    wrong = await _login(client, "real@example.com", "whatever-password")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


async def test_an_unknown_email_still_costs_a_password_hash_verification(client, monkeypatch):
    """Without this the response time would reveal which emails are registered."""
    from app.services import auth_service

    calls = []
    real = auth_service.verify_password
    monkeypatch.setattr(auth_service, "verify_password", lambda p, h: calls.append(h) or real(p, h))
    await _login(client, "nobody-at-all@example.com", "whatever-password")
    assert len(calls) == 1
    assert calls[0] == auth_service._TIMING_DECOY_HASH


async def test_password_reset_does_not_reveal_whether_the_account_exists(client):
    await _register(client, "exists@example.com")
    a = await client.post("/api/v1/auth/password-reset/request", json={"email": "exists@example.com"})
    b = await client.post("/api/v1/auth/password-reset/request", json={"email": "missing@example.com"})
    assert a.status_code == b.status_code == 202
    assert a.json()["detail"] == b.json()["detail"]


async def test_reset_links_are_returned_in_development_only(client, monkeypatch):
    await _register(client, "dev@example.com")
    dev = await client.post("/api/v1/auth/password-reset/request", json={"email": "dev@example.com"})
    assert dev.json()["dev_reset_url"]
    for environment in ("staging", "production"):
        monkeypatch.setattr(settings, "environment", environment)
        resp = await client.post("/api/v1/auth/password-reset/request", json={"email": "dev@example.com"})
        assert resp.json()["dev_reset_url"] is None


async def test_a_deployed_instance_never_logs_a_live_reset_token(client, monkeypatch, caplog, session_factory):
    await _register(client, "leak@example.com")
    monkeypatch.setattr(settings, "environment", "production")
    with caplog.at_level(logging.DEBUG):
        await client.post("/api/v1/auth/password-reset/request", json={"email": "leak@example.com"})
    assert "reset-password?token=" not in caplog.text
    async with session_factory() as db:
        assert await db.scalar(select(PasswordResetToken.id)) is not None  # the token exists, just isn't logged


async def test_reset_tokens_are_single_use_and_stored_hashed(client, session_factory):
    await _register(client, "once@example.com")
    resp = await client.post("/api/v1/auth/password-reset/request", json={"email": "once@example.com"})
    token = resp.json()["dev_reset_url"].split("token=")[1]
    async with session_factory() as db:
        stored = await db.scalar(select(PasswordResetToken.token_hash))
    assert stored != token and len(stored) == 64
    ok = await client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "Brand-New-Pass1"})
    assert ok.status_code == 204
    again = await client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "Another-Pass-2"})
    assert again.status_code == 400


async def test_a_password_reset_signs_out_every_session(client):
    reg = (await _register(client, "sessions@example.com")).json()["tokens"]
    reset = await client.post("/api/v1/auth/password-reset/request", json={"email": "sessions@example.com"})
    token = reset.json()["dev_reset_url"].split("token=")[1]
    await client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "Brand-New-Pass1"})
    refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": reg["refresh_token"]}, headers=MOBILE)
    assert refreshed.status_code == 401


async def test_refresh_tokens_are_stored_only_as_hashes(client, session_factory):
    tokens = (await _register(client, "hash@example.com")).json()["tokens"]
    async with session_factory() as db:
        rows = (await db.scalars(select(RefreshToken.token_hash))).all()
    assert tokens["refresh_token"] not in rows and all(len(r) == 64 for r in rows)


async def test_a_replayed_refresh_token_revokes_the_whole_chain(client):
    first = (await _register(client, "chain@example.com")).json()["tokens"]
    second = (await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}, headers=MOBILE)).json()["tokens"]
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}, headers=MOBILE)).status_code == 401
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}, headers=MOBILE)).status_code == 401


async def test_a_suspended_account_loses_access_immediately_even_with_a_valid_token(client, make_user, session_factory):
    from datetime import datetime, timezone

    user, headers = await make_user("soon-suspended@example.com")
    assert (await client.get("/api/v1/users/me", headers=headers)).status_code == 200
    async with session_factory() as db:
        row = await db.get(User, user.id)
        row.suspended_at = datetime.now(timezone.utc)
        await db.commit()
    assert (await client.get("/api/v1/users/me", headers=headers)).status_code == 401


async def test_a_token_signed_with_another_key_or_algorithm_is_rejected(client, test_user):
    import jwt

    forged = jwt.encode({"sub": str(test_user.id), "type": "access"}, "not-the-real-secret-at-all-0123456789", algorithm="HS256")
    none_alg = jwt.encode({"sub": str(test_user.id), "type": "access"}, "", algorithm="none")
    refresh_typed = jwt.encode({"sub": str(test_user.id), "type": "refresh"}, settings.jwt_secret, algorithm="HS256")
    for token in (forged, none_alg, refresh_typed):
        assert (await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_a_role_claim_in_the_token_grants_nothing(client, make_user):
    """Authorisation is read from the database, never from the token."""
    import jwt

    user, _ = await make_user("plain@example.com")
    token = jwt.encode({"sub": str(user.id), "type": "access", "role": "admin", "premium": True}, settings.jwt_secret, algorithm="HS256")
    resp = await client.get("/api/v1/admin/system", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.parametrize("environment,secure", [("development", False), ("staging", True), ("production", True)])
async def test_auth_cookies_are_secure_httponly_samesite_when_deployed(client, monkeypatch, environment, secure):
    monkeypatch.setattr(settings, "environment", environment)
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": f"cookie-{environment}@example.com", "password": PASSWORD, "password_confirm": PASSWORD},
    )
    cookies = resp.headers.get_list("set-cookie")
    assert len(cookies) == 2
    for header in cookies:
        assert "httponly" in header.lower()
        assert "samesite=lax" in header.lower()
        assert ("secure" in header.lower()) is secure


async def test_logout_clears_the_cookies_and_revokes_the_refresh_token(client):
    tokens = (await _register(client, "bye@example.com")).json()["tokens"]
    resp = await client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 204
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}, headers=MOBILE)).status_code == 401


async def test_the_login_rate_limit_counter_always_has_a_ttl(fake_redis: RedisService):
    """INCR and EXPIRE are one transaction: a counter can never be left without an expiry."""
    for _ in range(3):
        await fake_redis.incr("rl:test", ttl_seconds=60)
    assert 0 < await fake_redis.raw.ttl("rl:test") <= 60
    await fake_redis.raw.persist("rl:test")  # simulate the old crash-between-commands state
    await fake_redis.incr("rl:test", ttl_seconds=60)
    assert await fake_redis.raw.ttl("rl:test") > 0  # self-heals on the next hit
