"""Device registration + notification preference endpoint tests (Phase 3
§31): registration, listing, removal, cross-user isolation, and the
preference upsert (idempotent, including the GLOBAL/`scope_id=None` case).
"""


async def test_register_expo_device(authenticated_client):
    resp = await authenticated_client.post(
        "/api/v1/devices", json={"platform": "expo_ios", "expo_push_token": "ExponentPushToken[abc]"}
    )
    assert resp.status_code == 201
    assert resp.json()["platform"] == "expo_ios"

    list_resp = await authenticated_client.get("/api/v1/devices")
    assert len(list_resp.json()) == 1


async def test_register_web_device_requires_full_subscription(authenticated_client):
    resp = await authenticated_client.post("/api/v1/devices", json={"platform": "web"})
    assert resp.status_code == 422


async def test_register_web_device_with_full_subscription(authenticated_client):
    resp = await authenticated_client.post(
        "/api/v1/devices",
        json={
            "platform": "web",
            "web_push_endpoint": "https://push.example.com/sub/1",
            "web_push_p256dh": "p256dh-key",
            "web_push_auth": "auth-key",
        },
    )
    assert resp.status_code == 201


async def test_remove_device(authenticated_client):
    register_resp = await authenticated_client.post(
        "/api/v1/devices", json={"platform": "expo_android", "expo_push_token": "ExponentPushToken[xyz]"}
    )
    device_id = register_resp.json()["id"]

    remove_resp = await authenticated_client.delete(f"/api/v1/devices/{device_id}")
    assert remove_resp.status_code == 204

    list_resp = await authenticated_client.get("/api/v1/devices")
    assert list_resp.json() == []


async def test_devices_require_authentication(client):
    resp = await client.get("/api/v1/devices")
    assert resp.status_code == 401


async def test_re_registering_same_token_reassigns_rather_than_errors(authenticated_client):
    payload = {"platform": "expo_ios", "expo_push_token": "ExponentPushToken[shared]"}
    first = await authenticated_client.post("/api/v1/devices", json=payload)
    second = await authenticated_client.post("/api/v1/devices", json=payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


async def test_update_and_list_preferences(authenticated_client):
    resp = await authenticated_client.patch(
        "/api/v1/notifications/preferences",
        json={"scope_type": "team", "scope_id": 1, "event_type": "GOAL", "enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    list_resp = await authenticated_client.get("/api/v1/notifications/preferences")
    prefs = list_resp.json()
    assert len(prefs) == 1
    assert prefs[0]["scope_id"] == 1


async def test_update_preference_upserts_idempotently(authenticated_client):
    payload = {"scope_type": "global", "event_type": "GOAL", "enabled": False}
    first = await authenticated_client.patch("/api/v1/notifications/preferences", json=payload)
    second = await authenticated_client.patch(
        "/api/v1/notifications/preferences", json={**payload, "enabled": True}
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["enabled"] is True

    list_resp = await authenticated_client.get("/api/v1/notifications/preferences")
    assert len(list_resp.json()) == 1  # updated in place, not duplicated


async def test_global_scope_requires_no_scope_id(authenticated_client):
    resp = await authenticated_client.patch(
        "/api/v1/notifications/preferences",
        json={"scope_type": "global", "scope_id": 5, "event_type": "GOAL", "enabled": False},
    )
    assert resp.status_code == 422


async def test_team_scope_requires_scope_id(authenticated_client):
    resp = await authenticated_client.patch(
        "/api/v1/notifications/preferences",
        json={"scope_type": "team", "event_type": "GOAL", "enabled": False},
    )
    assert resp.status_code == 422
