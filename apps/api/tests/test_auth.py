"""Auth endpoint tests (Phase 3 §31): registration, login, refresh rotation
+ reuse detection, logout, profile/password management, password reset, and
rate limiting. Uses `X-Client: mobile` to get raw tokens back in the JSON
body where a test needs to control exactly which token it presents next,
rather than relying on the AsyncClient's own cookie jar.
"""

MOBILE = {"X-Client": "mobile"}


async def _register(client, email="new-user@example.com", password="Sup3rSecret!", **extra):
    payload = {"email": email, "password": password, "password_confirm": password, **extra}
    return await client.post("/api/v1/auth/register", json=payload, headers=MOBILE)


async def test_register_creates_user_and_sets_cookies(client):
    resp = await _register(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["user"]["email"] == "new-user@example.com"
    assert body["tokens"]["access_token"]
    assert body["tokens"]["refresh_token"]
    assert "access_token" in resp.cookies
    assert "refresh_token" in resp.cookies


async def test_register_without_mobile_header_omits_tokens_from_body(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "web-user@example.com",
            "password": "Sup3rSecret!",
            "password_confirm": "Sup3rSecret!",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["tokens"] is None
    assert "access_token" in resp.cookies


async def test_password_mismatch_is_rejected(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "x@example.com", "password": "Sup3rSecret!", "password_confirm": "Different!"},
    )
    assert resp.status_code == 422


async def test_duplicate_registration_returns_409(client):
    await _register(client, email="dupe@example.com")
    resp = await _register(client, email="dupe@example.com")
    assert resp.status_code == 409


async def test_login_success(client):
    await _register(client, email="login@example.com", password="Sup3rSecret!")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "Sup3rSecret!"},
        headers=MOBILE,
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "login@example.com"


async def test_login_with_invalid_password_returns_401(client):
    await _register(client, email="login2@example.com", password="Sup3rSecret!")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "login2@example.com", "password": "WrongPassword!"},
    )
    assert resp.status_code == 401


async def test_login_with_unknown_email_returns_401(client):
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever123"}
    )
    assert resp.status_code == 401


async def test_refresh_rotates_token_and_detects_reuse(client):
    register_resp = await _register(client, email="rotate@example.com", password="Sup3rSecret!")
    refresh_1 = register_resp.json()["tokens"]["refresh_token"]

    refresh_resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_1}, headers=MOBILE
    )
    assert refresh_resp.status_code == 200
    refresh_2 = refresh_resp.json()["tokens"]["refresh_token"]
    assert refresh_2 != refresh_1

    # Reusing the already-rotated-away token is rejected...
    reuse_resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_1})
    assert reuse_resp.status_code == 401

    # ...and revokes the whole chain, so even the *new* token stops working.
    chain_resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_2})
    assert chain_resp.status_code == 401


async def test_refresh_with_unknown_token_returns_401(client):
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert resp.status_code == 401


async def test_logout_revokes_refresh_token(client):
    register_resp = await _register(client, email="logout@example.com", password="Sup3rSecret!")
    refresh_token = register_resp.json()["tokens"]["refresh_token"]

    logout_resp = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert logout_resp.status_code == 204

    refresh_resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_resp.status_code == 401


async def test_get_me_requires_authentication(client):
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401


async def test_get_me_returns_current_user(authenticated_client, test_user):
    resp = await authenticated_client.get("/api/v1/users/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == test_user.email


async def test_update_me_changes_display_name(authenticated_client):
    resp = await authenticated_client.patch("/api/v1/users/me", json={"display_name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "New Name"


async def test_change_password_rejects_wrong_current_password(authenticated_client):
    resp = await authenticated_client.post(
        "/api/v1/users/me/password",
        json={"current_password": "wrong", "new_password": "BrandNewSecret1!"},
    )
    assert resp.status_code == 400


async def test_change_password_then_login_with_new_password(client):
    register_resp = await _register(client, email="changepw@example.com", password="Sup3rSecret!")
    access_token = register_resp.json()["tokens"]["access_token"]

    change_resp = await client.post(
        "/api/v1/users/me/password",
        json={"current_password": "Sup3rSecret!", "new_password": "BrandNewSecret1!"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert change_resp.status_code == 204

    old_login = await client.post(
        "/api/v1/auth/login", json={"email": "changepw@example.com", "password": "Sup3rSecret!"}
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/api/v1/auth/login", json={"email": "changepw@example.com", "password": "BrandNewSecret1!"}
    )
    assert new_login.status_code == 200


async def test_password_reset_flow(client):
    await _register(client, email="reset@example.com", password="Sup3rSecret!")

    request_resp = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "reset@example.com"}
    )
    assert request_resp.status_code == 202
    dev_url = request_resp.json()["dev_reset_url"]
    assert dev_url is not None
    token = dev_url.split("token=")[1]

    confirm_resp = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "ResetPassword1!"},
    )
    assert confirm_resp.status_code == 204

    login_resp = await client.post(
        "/api/v1/auth/login", json={"email": "reset@example.com", "password": "ResetPassword1!"}
    )
    assert login_resp.status_code == 200

    # A used reset token can't be replayed.
    replay_resp = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "AnotherPassword1!"},
    )
    assert replay_resp.status_code == 400


async def test_password_reset_does_not_reveal_account_existence(client):
    resp = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "no-such-account@example.com"}
    )
    assert resp.status_code == 202
    assert resp.json()["dev_reset_url"] is None


async def test_login_is_rate_limited_per_email(client):
    await _register(client, email="ratelimited@example.com", password="Sup3rSecret!")

    responses = []
    for _ in range(6):
        responses.append(
            await client.post(
                "/api/v1/auth/login",
                json={"email": "ratelimited@example.com", "password": "WrongPassword!"},
            )
        )

    assert [r.status_code for r in responses[:5]] == [401] * 5
    assert responses[5].status_code == 429
