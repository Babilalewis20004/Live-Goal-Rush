"""One continuous Phase 6b journey over the real HTTP API with the seeded mock data:

    log in -> open a match -> analytics -> comparison -> prediction -> comment -> react -> vote
    -> pay (signed webhook) -> premium detail -> cancel

Only the payment processor's callback is simulated (a correctly signed webhook), and the prediction job is
invoked directly instead of through Celery.
"""

from app.models.enums import UserRole
from app.services.billing.providers import sign_payload
from app.core.config import settings
from app.services.prediction_service import PredictionService
import json

from app.services.cache import CacheAside

API = "/api/v1"


async def test_the_whole_journey(seeded_client, make_user, session_factory, fake_redis):
    client = seeded_client
    fan, _ = await make_user("fan@example.com")  # created directly; the login below proves credentials work
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)

    # -- log in --------------------------------------------------------------------------------
    login = await client.post(f"{API}/auth/login", json={"email": "fan@example.com", "password": "Sup3rSecret!"}, headers={"X-Client": "mobile"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}

    # -- open a match ----------------------------------------------------------------------------
    upcoming = [m for m in (await client.get(f"{API}/matches/upcoming")).json() if m["status"] == "scheduled"]
    match = upcoming[0]
    assert (await client.get(f"{API}/matches/{match['id']}")).status_code == 200
    home_id = match["home_team"]["id"]

    # -- analytics: free view is public, longer history is not ---------------------------------------
    analytics = (await client.get(f"{API}/teams/{home_id}/analytics", headers=headers)).json()
    assert analytics["tier"] == "basic" and analytics["matches_considered"] > 0 and "locked" in analytics and analytics["locked"]
    assert (await client.get(f"{API}/teams/{home_id}/analytics?window=20", headers=headers)).status_code == 402
    comparison = (await client.get(f"{API}/matches/{match['id']}/comparison", headers=headers)).json()
    assert comparison["tier"] == "basic" and comparison["rows"] and comparison["home_team"]["id"] == home_id

    # -- prediction: not there until the job has run, then labelled and shaped ---------------------------------
    before = (await client.get(f"{API}/matches/{match['id']}/prediction", headers=headers)).json()
    assert before["status"] == "unavailable"
    async with session_factory() as db:
        generated = await PredictionService(db, CacheAside(fake_redis)).generate(match["id"])  # as the worker does: drops the cached "unavailable"
    assert generated.status == "available"
    prediction = (await client.get(f"{API}/matches/{match['id']}/prediction", headers=headers)).json()
    assert prediction["label"] == "Model estimate" and prediction["model_version"] == "poisson-v1"
    assert round(prediction["home_win"] + prediction["draw"] + prediction["away_win"], 2) == 1.0
    assert prediction["expected_home_goals"] is None  # free view
    assert prediction["generated_at"] and prediction["data_timestamp"]

    # -- community: comment, react, vote ---------------------------------------------------------------------------
    comment = await client.post(f"{API}/comments", json={"target_type": "match", "target_id": match["id"], "body": "This should be a good one"}, headers=headers)
    assert comment.status_code == 201
    listed = (await client.get(f"{API}/comments?target_type=match&target_id={match['id']}", headers=headers)).json()
    assert [c["body"] for c in listed["items"]] == ["This should be a good one"] and listed["items"][0]["mine"]
    reaction = (await client.put(f"{API}/reactions/match/{match['id']}", json={"kind": "heart"}, headers=headers)).json()
    assert reaction["mine"] == "heart" and reaction["counts"]["heart"] == 1

    poll = (await client.post(f"{API}/editor/polls", json={"question": "Who wins?", "kind": "match", "match_id": match["id"], "options": ["Home", "Draw", "Away"]}, headers=editor)).json()
    voted = (await client.post(f"{API}/polls/{poll['id']}/vote", json={"option_id": poll["options"][0]["id"]}, headers=headers)).json()
    assert voted["my_vote"] == poll["options"][0]["id"] and voted["total_votes"] == 1
    assert (await client.post(f"{API}/polls/{poll['id']}/vote", json={"option_id": poll["options"][1]["id"]}, headers=headers)).status_code == 409

    # -- the feed now knows about the conversation ----------------------------------------------------------------------------
    feed = (await client.get(f"{API}/feed", headers=headers)).json()
    assert any(i["reason"] == "community_match" and i["match"]["id"] == match["id"] for i in feed["items"])

    # -- pay: only the signed webhook upgrades the account -----------------------------------------------------------------------
    user_id = (await client.get(f"{API}/users/me", headers=headers)).json()["id"]
    checkout = await client.post(f"{API}/subscription/checkout", json={"plan_code": "premium_monthly"}, headers=headers)
    assert checkout.status_code == 200 and (await client.get(f"{API}/me/entitlements", headers=headers)).json()["premium"] is False
    body = json.dumps({"id": "evt_e2e", "type": "subscription.activated", "data": {
        "user_id": user_id, "plan_code": "premium_monthly", "subscription_id": "sub_e2e", "period_end": "2099-01-01T00:00:00+00:00"}}).encode()
    hook = await client.post(f"{API}/billing/webhook", content=body, headers={"X-Signature": sign_payload(body, settings.billing_webhook_secret)})
    assert hook.json() == {"result": "processed"}

    # -- premium detail --------------------------------------------------------------------------------------------------------------
    full = (await client.get(f"{API}/teams/{home_id}/analytics?window=20", headers=headers)).json()
    assert full["tier"] == "full" and full["locked"] == [] and "possession_pct" in full["possession"]
    full_comparison = (await client.get(f"{API}/matches/{match['id']}/comparison", headers=headers)).json()
    assert full_comparison["tier"] == "full" and len(full_comparison["rows"]) > len(comparison["rows"])
    detailed = (await client.get(f"{API}/matches/{match['id']}/prediction", headers=headers)).json()
    assert detailed["expected_home_goals"] is not None and detailed["factors"]["league_matches"] >= 0
    # and the same endpoints still serve the free view to someone who has not paid
    client.cookies.clear()  # login also set the auth cookie; an anonymous visitor has none
    stranger = (await client.get(f"{API}/matches/{match['id']}/prediction")).json()
    assert stranger["expected_home_goals"] is None

    # -- cancel: access continues until the period ends --------------------------------------------------------------------------
    cancelled = (await client.post(f"{API}/subscription/cancel", headers=headers)).json()
    assert cancelled["status"] == "cancelled" and cancelled["entitlements"]
    assert (await client.get(f"{API}/teams/{home_id}/analytics?window=20", headers=headers)).status_code == 200
    assert fan.id == user_id
