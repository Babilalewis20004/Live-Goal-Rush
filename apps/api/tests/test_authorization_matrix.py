"""Endpoint-by-endpoint authorisation audit (Phase 7 §16-17), driven by the OpenAPI schema so a new route can
never be exposed by accident: every operation is either on the explicit PUBLIC list below or must refuse an
anonymous caller; staff and admin routes must refuse ordinary users; and IDOR attempts against another
person's data must come back as 403/404 with nothing leaked.

If this file fails after you add an endpoint, decide deliberately: is it public (add it to PUBLIC), or does it
need `CurrentUserDep` / a role dependency?"""

import re

import pytest

from app.models.enums import UserRole

API = "/api/v1"

# -- the complete list of operations an anonymous caller may reach -------------------------------------------------
PUBLIC = {
    ("GET", "/api/v1/ads/placements"),
    ("GET", "/api/v1/articles"), ("GET", "/api/v1/articles/categories"), ("GET", "/api/v1/articles/tags"),
    ("GET", "/api/v1/articles/{slug}"), ("GET", "/api/v1/articles/{slug}/related"),
    ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/logout"), ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/register"), ("POST", "/api/v1/auth/password-reset/request"), ("POST", "/api/v1/auth/password-reset/confirm"),
    ("POST", "/api/v1/billing/webhook"),  # authenticated by HMAC signature, tested in test_billing*
    ("GET", "/api/v1/capabilities"),
    ("GET", "/api/v1/comments"),
    ("GET", "/api/v1/competitions"), ("GET", "/api/v1/competitions/{competition_id}"),
    ("GET", "/api/v1/competitions/{competition_id}/fixtures"), ("GET", "/api/v1/competitions/{competition_id}/news"),
    ("GET", "/api/v1/competitions/{competition_id}/seasons"), ("GET", "/api/v1/competitions/{competition_id}/standings"),
    ("GET", "/api/v1/competitions/{competition_id}/top-scorers"),
    ("GET", "/api/v1/discovery/home"), ("GET", "/api/v1/discovery/trending"), ("GET", "/api/v1/discovery/trending/{entity}"),
    ("POST", "/api/v1/engagement/view"),
    ("GET", "/api/v1/matches/live"), ("GET", "/api/v1/matches/today"), ("GET", "/api/v1/matches/upcoming"),
    ("GET", "/api/v1/matches/{match_id}"), ("GET", "/api/v1/matches/{match_id}/comparison"),
    ("GET", "/api/v1/matches/{match_id}/events"), ("GET", "/api/v1/matches/{match_id}/form"),
    ("GET", "/api/v1/matches/{match_id}/head-to-head"), ("GET", "/api/v1/matches/{match_id}/head-to-head/extended"),
    ("GET", "/api/v1/matches/{match_id}/insight-records"), ("GET", "/api/v1/matches/{match_id}/insights"),
    ("GET", "/api/v1/matches/{match_id}/lineups"), ("GET", "/api/v1/matches/{match_id}/news"),
    ("GET", "/api/v1/matches/{match_id}/players"), ("GET", "/api/v1/matches/{match_id}/prediction"),
    ("GET", "/api/v1/matches/{match_id}/statistics"),
    ("GET", "/api/v1/me/entitlements"),  # anonymous callers simply get the empty set
    ("GET", "/api/v1/media/{public_id}/{variant}"),
    ("GET", "/api/v1/notifications/vapid-public-key"),
    ("GET", "/api/v1/players/{player_id}"), ("GET", "/api/v1/players/{player_id}/analytics"),
    ("GET", "/api/v1/players/{player_id}/insights"), ("GET", "/api/v1/players/{player_id}/news"),
    ("GET", "/api/v1/players/{player_id}/statistics"),
    ("GET", "/api/v1/polls"), ("GET", "/api/v1/polls/{poll_id}"),
    ("GET", "/api/v1/predictions/evaluation"),
    ("GET", "/api/v1/profiles/{user_id}"),  # only ever returns a profile its owner made public
    ("GET", "/api/v1/reactions/{target_type}/{target_id}"),
    ("GET", "/api/v1/search"), ("GET", "/api/v1/search/popular"),
    ("GET", "/api/v1/search/suggestions"), ("POST", "/api/v1/search/track"),
    ("GET", "/api/v1/subscription/plans"),
    ("GET", "/api/v1/teams/{team_id}"), ("GET", "/api/v1/teams/{team_id}/analytics"),
    ("GET", "/api/v1/teams/{team_id}/fixtures"), ("GET", "/api/v1/teams/{team_id}/form"),
    ("GET", "/api/v1/teams/{team_id}/form/extended"), ("GET", "/api/v1/teams/{team_id}/injuries"),
    ("GET", "/api/v1/teams/{team_id}/insight-records"), ("GET", "/api/v1/teams/{team_id}/insights"),
    ("GET", "/api/v1/teams/{team_id}/news"), ("GET", "/api/v1/teams/{team_id}/players"),
    ("GET", "/api/v1/teams/{team_id}/results"), ("GET", "/api/v1/teams/{team_id}/statistics"),
}

# Reachable by any signed-in user; refused to staff-only. Everything under these prefixes needs a staff role.
EDITOR_PREFIXES = (f"{API}/editor/", f"{API}/moderation/")
ADMIN_ONLY = lambda method, path: path.startswith(f"{API}/admin/") or re.fullmatch(rf"{API}/moderation/users/\{{user_id\}}/(un)?suspend", path)  # noqa: E731


def _all_operations():
    from app.main import app

    spec = app.openapi()
    found = []
    for path, item in spec["paths"].items():
        if not path.startswith(API):
            continue
        for method in item:
            if method.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                found.append((method.upper(), path))
    return sorted(found)


def concrete(path: str) -> str:
    """Fill path parameters with plausible values."""
    return re.sub(r"\{(\w+)\}", lambda m: "1" if m.group(1).endswith("id") else ("article" if m.group(1) == "target_type" else "x"), path)


ALL = _all_operations()
PROTECTED = [op for op in ALL if op not in PUBLIC]


def test_the_public_list_matches_reality():
    """No stale entries: everything listed as public exists."""
    assert PUBLIC - set(ALL) == set(), "PUBLIC lists operations that no longer exist"


@pytest.mark.parametrize("method,path", PROTECTED, ids=[f"{m} {p}" for m, p in PROTECTED])
async def test_every_non_public_operation_refuses_anonymous_callers(client, method, path):
    resp = await client.request(method, concrete(path), json={} if method in ("POST", "PUT", "PATCH") else None)
    assert resp.status_code == 401, f"{method} {path} answered {resp.status_code} to an anonymous caller"


# Answer 4xx by design when given nothing: /auth/refresh without a token is 401 "missing refresh token".
NO_CREDENTIAL_CHECK = {("POST", "/api/v1/billing/webhook"), ("POST", "/api/v1/auth/refresh")}


@pytest.mark.parametrize("method,path", [op for op in ALL if op in PUBLIC and op not in NO_CREDENTIAL_CHECK], ids=lambda v: str(v))
async def test_public_operations_never_demand_credentials(client, method, path):
    resp = await client.request(method, concrete(path), json={} if method in ("POST", "PUT", "PATCH") else None)
    assert resp.status_code not in (401, 403), f"{method} {path} is listed public but answered {resp.status_code}"


STAFF = [op for op in ALL if op[1].startswith(EDITOR_PREFIXES) or ADMIN_ONLY(*reversed(op))]


@pytest.mark.parametrize("method,path", STAFF, ids=[f"{m} {p}" for m, p in STAFF])
async def test_staff_routes_refuse_ordinary_signed_in_users(client, make_user, method, path):
    _u, headers = await make_user("plain@example.com")
    resp = await client.request(method, concrete(path), headers=headers, json={} if method in ("POST", "PUT", "PATCH") else None)
    assert resp.status_code == 403, f"{method} {path} answered {resp.status_code} to a plain user"


ADMIN = [(m, p) for m, p in STAFF if ADMIN_ONLY(m, p)]


@pytest.mark.parametrize("method,path", ADMIN, ids=[f"{m} {p}" for m, p in ADMIN])
@pytest.mark.parametrize("role", [UserRole.AUTHOR, UserRole.EDITOR])
async def test_admin_routes_refuse_every_other_role(client, make_user, method, path, role):
    _u, headers = await make_user(f"{role.value}@example.com", role)
    resp = await client.request(method, concrete(path), headers=headers, json={"reason": "x"} if method == "POST" else None)
    assert resp.status_code == 403, f"{method} {path} answered {resp.status_code} to {role.value}"


# -- IDOR: one person must never reach another's data -----------------------------------------------------------------


async def test_devices_belong_to_their_owner(client, make_user):
    alice, a = await make_user("alice@example.com")
    _bob, b = await make_user("bob@example.com")
    reg = await client.post(f"{API}/devices", json={"platform": "expo_ios", "expo_push_token": "ExponentPushToken[alice-device]"}, headers=a)
    assert reg.status_code in (200, 201)
    device_id = reg.json()["id"]
    # Deletion is scoped to the caller's own rows: Bob's request is a no-op, not a deletion of Alice's device.
    assert (await client.delete(f"{API}/devices/{device_id}", headers=b)).status_code in (204, 403, 404)
    assert [d["id"] for d in (await client.get(f"{API}/devices", headers=a)).json()] == [device_id]
    assert (await client.get(f"{API}/devices", headers=b)).json() == []
    assert alice


async def test_favourites_and_preferences_are_per_user(client, make_user, seeded_client, lookup):
    from app.models.team import Team

    team_id = await lookup(Team, "Arsenal")
    _a, a = await make_user("alice@example.com")
    _b, b = await make_user("bob@example.com")
    assert (await client.post(f"{API}/favourites/teams/{team_id}", headers=a)).status_code in (200, 201, 204)
    assert (await client.get(f"{API}/favourites", headers=b)).json()["teams"] == []
    patched = await client.patch(f"{API}/notifications/preferences", json={"scope_type": "team", "scope_id": team_id, "event_type": "GOAL", "enabled": False}, headers=a)
    assert patched.status_code == 200, patched.text
    assert len((await client.get(f"{API}/notifications/preferences", headers=a)).json()) == 1
    assert (await client.get(f"{API}/notifications/preferences", headers=b)).json() == []


async def test_a_user_id_in_the_path_or_body_never_selects_someone_elses_account(client, make_user):
    alice, a = await make_user("alice@example.com")
    bob, b = await make_user("bob@example.com")
    for path in (f"/users/me?user_id={alice.id}", f"/users/me/profile?user_id={alice.id}", f"/subscription?user_id={alice.id}", f"/me/entitlements?user_id={alice.id}"):
        body = (await client.get(f"{API}{path}", headers=b)).text
        assert "alice" not in body.lower(), path
    patched = await client.patch(f"{API}/users/me", json={"display_name": "Mallory", "id": alice.id, "user_id": alice.id, "role": "admin", "email": "x@evil.example"}, headers=b)
    assert patched.status_code == 200
    me_b = (await client.get(f"{API}/users/me", headers=b)).json()
    me_a = (await client.get(f"{API}/users/me", headers=a)).json()
    assert me_b["id"] == bob.id and me_b["role"] == "user" and me_b["email"] == "bob@example.com"
    assert me_a["display_name"] != "Mallory"


async def test_profiles_are_invisible_until_their_owner_publishes_them(client, make_user):
    alice, a = await make_user("alice@example.com")
    _b, b = await make_user("bob@example.com")
    assert (await client.get(f"{API}/profiles/{alice.id}", headers=b)).status_code == 404
    assert (await client.get(f"{API}/profiles/{alice.id}")).status_code == 404
    assert (await client.post(f"{API}/profiles/{alice.id}/report", json={"reason": "spam"}, headers=b)).status_code == 404  # a private profile can't be probed via reports either


async def test_comments_can_only_be_changed_or_deleted_by_their_author(client, make_user, session_factory):
    from app.models.community import Comment
    from app.models.enums import CommentStatus, CommentTarget

    alice, a = await make_user("alice@example.com")
    _b, b = await make_user("bob@example.com")
    async with session_factory() as db:
        db.add(Comment(user_id=alice.id, target_type=CommentTarget.MATCH, target_id=1, body="alice's words", status=CommentStatus.VISIBLE))
        await db.commit()
    assert (await client.patch(f"{API}/comments/1", json={"body": "hijacked"}, headers=b)).status_code in (403, 404)
    assert (await client.delete(f"{API}/comments/1", headers=b)).status_code in (403, 404)
    async with session_factory() as db:
        assert (await db.get(Comment, 1)).body == "alice's words"


async def test_unpublished_articles_and_other_authors_drafts_are_not_reachable(client, make_user):
    ed, e = await make_user("ed@example.com", UserRole.EDITOR)
    _other, o = await make_user("other-ed@example.com", UserRole.AUTHOR)
    created = await client.post(f"{API}/editor/articles", json={"title": "Secret draft", "body_html": "<p>embargoed</p>"}, headers=e)
    assert created.status_code in (200, 201), created.text
    article = created.json()
    assert (await client.get(f"{API}/articles/{article['slug']}")).status_code == 404  # public: drafts do not exist
    assert (await client.get(f"{API}/editor/articles/{article['id']}", headers=o)).status_code in (403, 404)  # another author can't open it
    assert (await client.patch(f"{API}/editor/articles/{article['id']}", json={"title": "stolen"}, headers=o)).status_code in (403, 404)
    assert (await client.delete(f"{API}/editor/articles/{article['id']}", headers=o)).status_code in (403, 404)
    assert ed


async def test_the_subscription_summary_is_always_the_callers_own(client, make_user):
    import json
    import time

    from app.core.config import settings
    from app.services.billing.providers import sign_payload

    payer, p = await make_user("payer@example.com")
    _free, f = await make_user("free@example.com")
    payload = json.dumps({"id": "e", "created": int(time.time()), "type": "subscription.activated", "data": {"user_id": payer.id, "plan_code": "premium_monthly", "subscription_id": "sub_p", "customer_id": "cus_p", "period_end": "2099-01-01T00:00:00+00:00"}}).encode()
    await client.post(f"{API}/billing/webhook", content=payload, headers={"X-Signature": sign_payload(payload, settings.billing_webhook_secret), "Content-Type": "application/json"})
    assert (await client.get(f"{API}/subscription", headers=p)).json()["status"] == "active"
    assert (await client.get(f"{API}/subscription", headers=f)).json()["status"] == "none"
    assert (await client.post(f"{API}/subscription/cancel", headers=f)).status_code == 404  # can't cancel someone else's, or a non-existent one


async def test_internal_endpoints_are_not_publicly_reachable_through_the_api_prefix(client):
    """Prometheus metrics are served on the API's own port for scraping on the private network; the reverse proxy
    refuses /metrics from outside (deploy/nginx/nginx.conf). Nothing under /api/v1 exposes operations data."""
    for path in ("/metrics", "/api/v1/metrics", "/api/v1/debug", "/api/v1/admin", "/api/v1/internal", "/docs-internal"):
        body = (await client.get(path)).text
        if path != "/metrics":
            assert "process_cpu_seconds" not in body
