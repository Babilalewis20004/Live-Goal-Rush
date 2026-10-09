"""Subscription consistency under hostile delivery (Phase 7 §18-19): concurrent duplicates, out-of-order and
delayed events, replays, and entitlement checks that no client-controlled input can influence."""

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models.billing import PaymentEvent, Subscription
from app.models.enums import PaymentEventStatus, SubscriptionStatus
from app.services.billing.providers import sign_payload

API = "/api/v1"
NOW = int(time.time())


def body(event_id, kind, user_id=None, created=None, **data):
    doc = {"id": event_id, "type": kind, "data": {"user_id": user_id, **data}}
    if created is not None:
        doc["created"] = created
    return json.dumps(doc).encode()


async def send(client, payload: bytes):
    headers = {"X-Signature": sign_payload(payload, settings.billing_webhook_secret), "Content-Type": "application/json"}
    return await client.post(f"{API}/billing/webhook", content=payload, headers=headers)


def at(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


async def activate(client, user_id, created=NOW, event_id="evt_act", days=30, sub_id="sub_x"):
    return await send(client, body(event_id, "subscription.activated", user_id, created, plan_code="premium_monthly", subscription_id=sub_id, customer_id="cus_x", period_end=at(days)))


async def current(session_factory) -> Subscription:
    async with session_factory() as db:
        return await db.scalar(select(Subscription))


async def test_the_same_event_delivered_concurrently_is_applied_exactly_once(client, make_user, session_factory):
    user, _ = await make_user("race@example.com")
    payload = body("evt_race", "subscription.activated", user.id, NOW, plan_code="premium_monthly", subscription_id="sub_race", customer_id="cus", period_end=at(30))
    results = await asyncio.gather(*[send(client, payload) for _ in range(8)])
    assert all(r.status_code == 200 for r in results)
    outcomes = sorted(r.json()["result"] for r in results)
    assert outcomes.count("processed") == 1 and outcomes.count("duplicate") == 7
    async with session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(Subscription)) == 1
        assert await db.scalar(select(func.count()).select_from(PaymentEvent)) == 1


async def test_a_replayed_valid_webhook_changes_nothing(client, make_user, session_factory):
    user, _ = await make_user("replay@example.com")
    payload = body("evt_replay", "subscription.activated", user.id, NOW, plan_code="premium_monthly", subscription_id="sub_r", customer_id="c", period_end=at(30))
    first = await send(client, payload)
    before = await current(session_factory)
    second = await send(client, payload)
    assert (first.json()["result"], second.json()["result"]) == ("processed", "duplicate")
    after = await current(session_factory)
    assert (before.status, before.current_period_end, before.updated_at) == (after.status, after.current_period_end, after.updated_at)


async def test_a_delayed_cancellation_cannot_undo_a_newer_renewal(client, make_user, session_factory):
    user, _ = await make_user("late-cancel@example.com")
    await activate(client, user.id, created=NOW - 1000, days=30)
    await send(client, body("evt_cancel", "subscription.cancelled", user.id, NOW - 500, subscription_id="sub_x", period_end=at(30)))
    # the user resubscribed / the period renewed afterwards ...
    await send(client, body("evt_renew", "subscription.renewed", user.id, NOW, subscription_id="sub_x", period_end=at(60)))
    # ... and a *retried older* cancel event is finally delivered
    late = await send(client, body("evt_cancel_retry", "subscription.cancelled", user.id, NOW - 400, subscription_id="sub_x", period_end=at(30)))
    sub = await current(session_factory)
    assert late.json()["result"] == "ignored"
    assert sub.status == SubscriptionStatus.ACTIVE and sub.cancel_at_period_end is False
    assert sub.current_period_end > datetime.now(timezone.utc) + timedelta(days=50)


async def test_an_old_period_end_never_shortens_a_paid_period(client, make_user, session_factory):
    user, _ = await make_user("period@example.com")
    await activate(client, user.id, created=NOW - 100, days=60)
    # no timestamp on this one: ordering can't help, but the period must still only grow
    await send(client, body("evt_old_renew", "subscription.renewed", user.id, None, subscription_id="sub_x", period_end=at(10)))
    sub = await current(session_factory)
    assert sub.current_period_end > datetime.now(timezone.utc) + timedelta(days=55)


async def test_a_late_failed_payment_for_an_old_invoice_does_not_downgrade_a_paid_subscription(client, make_user, session_factory):
    user, _ = await make_user("late-fail@example.com")
    await activate(client, user.id, created=NOW - 1000)
    await send(client, body("evt_paid", "subscription.renewed", user.id, NOW, subscription_id="sub_x", period_end=at(60)))
    await send(client, body("evt_failed_old", "payment.failed", user.id, NOW - 200, subscription_id="sub_x"))
    assert (await current(session_factory)).status == SubscriptionStatus.ACTIVE


async def test_events_are_applied_in_processor_order_not_arrival_order(client, make_user, session_factory):
    """Delivered newest-first: the final state is the newest event's, whichever arrives last."""
    user, _ = await make_user("order@example.com")
    await activate(client, user.id, created=NOW - 3000)
    await send(client, body("e3", "subscription.expired", user.id, NOW - 100, subscription_id="sub_x"))
    stale = await send(client, body("e2", "subscription.renewed", user.id, NOW - 2000, subscription_id="sub_x", period_end=at(30)))
    assert stale.json()["result"] == "ignored"
    assert (await current(session_factory)).status == SubscriptionStatus.EXPIRED


async def test_a_stale_event_is_recorded_as_ignored_with_a_reason(client, make_user, session_factory):
    user, _ = await make_user("reason@example.com")
    await activate(client, user.id, created=NOW)
    await send(client, body("evt_stale", "payment.failed", user.id, NOW - 500, subscription_id="sub_x"))
    async with session_factory() as db:
        row = await db.scalar(select(PaymentEvent).where(PaymentEvent.event_id == "evt_stale"))
    assert row.status == PaymentEventStatus.IGNORED and row.error == "stale event"


async def test_an_expired_subscription_stops_granting_access_even_if_a_renewal_event_never_arrives(client, make_user, session_factory):
    from app.services.billing.entitlements import entitlements_for

    user, _ = await make_user("lapsed@example.com")
    await activate(client, user.id, days=-30)  # period ended a month ago, beyond the grace window
    async with session_factory() as db:
        assert await entitlements_for(db, user) == frozenset()


async def test_entitlements_are_identical_from_every_device(client, make_user):
    user, headers = await make_user("devices@example.com")
    await activate(client, user.id)
    from app.core.security import create_access_token

    phone = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    laptop = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    a = (await client.get(f"{API}/me/entitlements", headers=phone)).json()
    b = (await client.get(f"{API}/me/entitlements", headers=laptop)).json()
    assert a == b and a["premium"] is True


# -- premium cannot be unlocked from the client ----------------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {"params": {"premium": "true", "entitlements": "extended_history", "tier": "premium"}},
        {"headers": {"X-Premium": "1", "X-Entitlements": "extended_history", "X-User-Role": "admin"}},
        {"cookies": {"premium": "1", "entitlements": "extended_history", "is_premium": "true"}},
    ],
    ids=["query-params", "headers", "cookies"],
)
async def test_premium_endpoints_stay_closed_whatever_the_client_claims(seeded_client, make_user, extra, get_match_id):
    _user, headers = await make_user("free@example.com")
    match_id = await get_match_id("epl-3")
    merged = {**headers, **extra.get("headers", {})}
    resp = await seeded_client.get(f"{API}/matches/{match_id}/head-to-head/extended", headers=merged, params=extra.get("params"), cookies=extra.get("cookies"))
    assert resp.status_code == 402


async def test_a_forged_token_claiming_premium_does_not_open_premium_endpoints(seeded_client, make_user, get_match_id):
    import jwt

    user, _ = await make_user("claims@example.com")
    forged = jwt.encode(
        {"sub": str(user.id), "type": "access", "premium": True, "entitlements": ["extended_history", "advanced_analytics"], "role": "admin",
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.jwt_secret, algorithm="HS256",
    )
    match_id = await get_match_id("epl-3")
    resp = await seeded_client.get(f"{API}/matches/{match_id}/head-to-head/extended", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 402
    assert (await seeded_client.get(f"{API}/me/entitlements", headers={"Authorization": f"Bearer {forged}"})).json()["entitlements"] == []


async def test_the_client_confirming_a_payment_grants_nothing(client, make_user):
    """There is no endpoint a browser can call to say 'I paid'; checkout only returns a URL."""
    _user, headers = await make_user("claims-paid@example.com")
    checkout = await client.post(f"{API}/subscription/checkout", json={"plan_code": "premium_monthly"}, headers=headers)
    assert checkout.status_code == 200
    for path in ("/subscription/confirm", "/subscription/activate", "/billing/success", "/me/entitlements/grant"):
        assert (await client.post(f"{API}{path}", headers=headers, json={"paid": True})).status_code in (404, 405)
    assert (await client.get(f"{API}/me/entitlements", headers=headers)).json()["premium"] is False


async def test_webhooks_without_a_valid_signature_are_rejected_even_with_a_plausible_body(client, make_user):
    user, _ = await make_user("nosig@example.com")
    payload = body("evt_unsigned", "subscription.activated", user.id, NOW, plan_code="premium_monthly", subscription_id="s", period_end=at(30))
    for headers in ({}, {"X-Signature": "t=1,v1=deadbeef"}, {"X-Signature": sign_payload(payload, "wrong-secret-entirely")}):
        resp = await client.post(f"{API}/billing/webhook", content=payload, headers={**headers, "Content-Type": "application/json"})
        assert resp.status_code == 400
    assert (await client.get(f"{API}/me/entitlements", headers=(await make_user("other@example.com"))[1])).json()["premium"] is False


async def test_oversized_webhook_bodies_are_refused(client):
    resp = await client.post(f"{API}/billing/webhook", content=b"{" + b" " * (300 * 1024) + b"}", headers={"Content-Type": "application/json"})
    assert resp.status_code == 413


async def test_a_payment_provider_outage_at_checkout_is_a_clean_502_and_creates_nothing(client, make_user, session_factory, monkeypatch):
    from app.services.billing import providers

    async def down(self, **_kwargs):
        raise providers.ProviderError("payment provider unreachable")

    monkeypatch.setattr(providers.TestBillingProvider, "create_checkout", down)
    _user, headers = await make_user("unlucky@example.com")
    resp = await client.post(f"{API}/subscription/checkout", json={"plan_code": "premium_monthly"}, headers=headers)
    assert resp.status_code == 502
    async with session_factory() as db:
        assert (await db.scalar(select(func.count()).select_from(Subscription))) == 0
    assert (await client.get(f"{API}/me/entitlements", headers=headers)).json()["premium"] is False
    # and the same user can simply try again once the provider is back
    monkeypatch.undo()
    assert (await client.post(f"{API}/subscription/checkout", json={"plan_code": "premium_monthly"}, headers=headers)).status_code == 200
