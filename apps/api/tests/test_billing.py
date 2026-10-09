"""Subscriptions, entitlements, webhooks and ads (Phase 6b)."""

import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models.billing import PaymentEvent, Subscription
from app.models.enums import PaymentEventStatus, SubscriptionStatus
from app.services.billing import entitlements as ent
from app.services.billing.providers import InvalidSignature, sign_payload, verify_signature
from app.services.billing.service import BillingService
from app.worker.analytics_tasks import expire_lapsed_subscriptions_once

API = "/api/v1"
SECRET = settings.billing_webhook_secret


def event(event_id, kind, user_id=None, **data):
    body = {"id": event_id, "type": kind, "data": {"user_id": user_id, **data}}
    return json.dumps(body).encode()


async def send(client, payload: bytes, secret=SECRET, ts=None, header=None):
    sig = header if header is not None else sign_payload(payload, secret, ts)
    return await client.post(f"{API}/billing/webhook", content=payload, headers={"X-Signature": sig, "Content-Type": "application/json"})


def period(days=30):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


async def activate(client, user_id, event_id="evt_1", sub_id="sub_1", plan="premium_monthly", days=30):
    return await send(client, event(event_id, "subscription.activated", user_id, plan_code=plan, subscription_id=sub_id, customer_id="cus_1", period_end=period(days)))


# -- signature scheme ---------------------------------------------------------------------------------


def test_signature_accepts_valid_and_rejects_everything_else():
    body = b'{"id":"e"}'
    verify_signature(body, sign_payload(body, "s"), "s", 300)
    for header in (None, "", "garbage", "t=abc,v1=ff", sign_payload(body, "wrong")):
        with pytest.raises(InvalidSignature):
            verify_signature(body, header, "s", 300)
    with pytest.raises(InvalidSignature):  # tampered body
        verify_signature(b'{"id":"x"}', sign_payload(body, "s"), "s", 300)
    with pytest.raises(InvalidSignature):  # replay of an old, validly signed request
        verify_signature(body, sign_payload(body, "s", int(time.time()) - 3600), "s", 300)


# -- plans and checkout ---------------------------------------------------------------------------------


async def test_plans_are_public_and_priced_in_minor_units(client):
    plans = (await client.get(f"{API}/subscription/plans")).json()
    assert [p["code"] for p in plans] == ["premium_monthly", "premium_yearly"]
    assert all(p["currency"] == "GBP" and set(p["entitlements"]) == set(ent.PREMIUM_ENTITLEMENTS) for p in plans)
    assert (await client.get(f"{API}/subscription/plans")).json() == plans  # seeding is idempotent


async def test_checkout_requires_login_and_grants_nothing(client, make_user):
    assert (await client.post(f"{API}/subscription/checkout", json={"plan_code": "premium_monthly"})).status_code == 401
    _, headers = await make_user("fan@example.com")
    r = await client.post(f"{API}/subscription/checkout", json={"plan_code": "premium_monthly"}, headers=headers)
    assert r.status_code == 200 and r.json()["url"].startswith("https://") and r.json()["session_id"]
    assert (await client.get(f"{API}/me/entitlements", headers=headers)).json()["entitlements"] == []  # only the webhook activates
    assert (await client.get(f"{API}/subscription", headers=headers)).json()["status"] == "none"
    assert (await client.post(f"{API}/subscription/checkout", json={"plan_code": "nope"}, headers=headers)).status_code == 404


# -- webhook authentication ---------------------------------------------------------------------------


async def test_unsigned_forged_tampered_and_stale_webhooks_are_rejected_and_change_nothing(client, make_user, session_factory):
    user, headers = await make_user("fan@example.com")
    body = event("evt_x", "subscription.activated", user.id, plan_code="premium_monthly", subscription_id="s", period_end=period())
    assert (await client.post(f"{API}/billing/webhook", content=body)).status_code == 400
    assert (await send(client, body, secret="not-the-secret")).status_code == 400
    assert (await send(client, body, ts=int(time.time()) - 7200)).status_code == 400
    ok_sig = sign_payload(body, SECRET)
    assert (await send(client, body + b" ", header=ok_sig)).status_code == 400  # signature does not cover a modified body
    assert (await client.get(f"{API}/me/entitlements", headers=headers)).json()["entitlements"] == []
    async with session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(PaymentEvent)) == 0
        assert await db.scalar(select(func.count()).select_from(Subscription)) == 0


async def test_webhook_is_refused_when_the_test_provider_is_used_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    r = await send(client, event("e", "subscription.activated", 1))
    assert r.status_code == 503


# -- activation, idempotency, retries ----------------------------------------------------------------------


async def test_activation_grants_entitlements_and_is_idempotent(client, make_user, session_factory):
    user, headers = await make_user("fan@example.com")
    first = await activate(client, user.id)
    assert first.status_code == 200 and first.json() == {"result": "processed"}
    ents = (await client.get(f"{API}/me/entitlements", headers=headers)).json()
    assert ents["premium"] and set(ents["entitlements"]) == set(ent.PREMIUM_ENTITLEMENTS)
    sub = (await client.get(f"{API}/subscription", headers=headers)).json()
    assert sub["status"] == "active" and sub["plan"] == "premium_monthly" and not sub["cancel_at_period_end"]

    again = await activate(client, user.id)  # the processor redelivers
    assert again.json() == {"result": "duplicate"}
    renamed = await activate(client, user.id, event_id="evt_2")  # a different event for the same subscription
    assert renamed.json() == {"result": "processed"}
    async with session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(Subscription)) == 1
        assert await db.scalar(select(func.count()).select_from(PaymentEvent)) == 2


async def test_premium_features_open_after_payment_and_stay_closed_before(client, make_user):
    user, headers = await make_user("fan@example.com")
    r = await client.get(f"{API}/teams/1/analytics?window=20", headers=headers)  # 402 before 404: gating is checked first
    assert r.status_code == 402 and r.json()["detail"]["entitlement"] == ent.EXTENDED_HISTORY
    await activate(client, user.id)
    after = await client.get(f"{API}/teams/1/analytics?window=20", headers=headers)
    assert after.status_code == 404  # now allowed through to the (non-existent) team


async def test_a_failed_event_is_recorded_then_retried_successfully(client, make_user, session_factory, monkeypatch):
    user, headers = await make_user("fan@example.com")
    original = BillingService._apply
    calls = {"n": 0}

    async def flaky(self, ev):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database hiccup")
        return await original(self, ev)

    monkeypatch.setattr(BillingService, "_apply", flaky)
    assert (await activate(client, user.id)).status_code == 500  # processor will retry
    async with session_factory() as db:
        row = (await db.execute(select(PaymentEvent))).scalar_one()
        assert row.status == PaymentEventStatus.FAILED and "hiccup" in row.error
    assert (await client.get(f"{API}/me/entitlements", headers=headers)).json()["entitlements"] == []
    retry = await activate(client, user.id)
    assert retry.json() == {"result": "processed"}
    async with session_factory() as db:
        row = (await db.execute(select(PaymentEvent))).scalar_one()
        assert row.status == PaymentEventStatus.PROCESSED and row.attempts == 2 and row.error is None
    assert (await client.get(f"{API}/subscription", headers=headers)).json()["status"] == "active"


async def test_events_for_unknown_users_or_subscriptions_are_acknowledged_but_ignored(client):
    assert (await activate(client, 424242)).json() == {"result": "ignored"}
    gone = await send(client, event("evt_r", "subscription.renewed", None, subscription_id="never-seen", period_end=period()))
    assert gone.json() == {"result": "ignored"}
    unknown_type = await send(client, event("evt_u", "something.else", None))
    assert unknown_type.status_code == 200


async def test_the_audit_row_stores_ids_and_amounts_not_card_data(client, make_user, session_factory):
    user, _ = await make_user("fan@example.com")
    raw = {"id": "evt_s", "type": "subscription.activated", "data": {"user_id": user.id, "plan_code": "premium_monthly", "subscription_id": "s1",
           "period_end": period(), "card_number": "4242424242424242", "cvc": "123"}}
    await send(client, json.dumps(raw).encode())
    async with session_factory() as db:
        stored = json.dumps((await db.execute(select(PaymentEvent))).scalar_one().payload)
    assert "4242" not in stored and "cvc" not in stored and "subscription_id" in stored


# -- cancel, renew, fail, expire ---------------------------------------------------------------------------


async def test_cancel_keeps_premium_until_the_period_ends(client, make_user, session_factory):
    user, headers = await make_user("fan@example.com")
    assert (await client.post(f"{API}/subscription/cancel", headers=headers)).status_code == 404  # nothing to cancel
    await activate(client, user.id)
    r = await client.post(f"{API}/subscription/cancel", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["cancel_at_period_end"] is True
    assert r.json()["entitlements"]  # still Premium for the period they paid for
    assert (await client.post(f"{API}/subscription/cancel", headers=headers)).status_code == 200  # idempotent
    async with session_factory() as db:  # the period passes
        sub = (await db.execute(select(Subscription))).scalar_one()
        sub.current_period_end = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    assert (await client.get(f"{API}/me/entitlements", headers=headers)).json()["entitlements"] == []
    assert (await client.post(f"{API}/subscription/checkout", json={"plan_code": "premium_monthly"}, headers=headers)).status_code == 200  # can resubscribe


async def test_cannot_start_a_second_subscription_while_one_is_running(client, make_user):
    user, headers = await make_user("fan@example.com")
    await activate(client, user.id)
    assert (await client.post(f"{API}/subscription/checkout", json={"plan_code": "premium_yearly"}, headers=headers)).status_code == 409


async def test_renewal_extends_and_payment_failure_gives_a_grace_period_then_access_ends(client, make_user, session_factory):
    user, headers = await make_user("fan@example.com")
    await activate(client, user.id, days=-1)  # the period ended yesterday and no renewal arrived yet
    assert (await client.get(f"{API}/me/entitlements", headers=headers)).json()["premium"] is True  # inside the grace window
    failed = await send(client, event("evt_f", "payment.failed", None, subscription_id="sub_1", amount_minor=499, currency="GBP"))
    assert failed.json() == {"result": "processed"}
    assert (await client.get(f"{API}/subscription", headers=headers)).json()["status"] == "past_due"
    assert (await client.get(f"{API}/me/entitlements", headers=headers)).json()["premium"] is True  # still within grace
    async with session_factory() as db:
        sub = (await db.execute(select(Subscription))).scalar_one()
        sub.current_period_end = datetime.now(timezone.utc) - timedelta(days=settings.billing_grace_days + 1)
        await db.commit()
    assert (await client.get(f"{API}/me/entitlements", headers=headers)).json()["premium"] is False
    renewed = await send(client, event("evt_n", "subscription.renewed", None, subscription_id="sub_1", period_end=period()))
    assert renewed.json() == {"result": "processed"}
    assert (await client.get(f"{API}/subscription", headers=headers)).json()["status"] == "active"
    assert (await client.get(f"{API}/me/entitlements", headers=headers)).json()["premium"] is True


async def test_expired_event_and_housekeeping_job(client, make_user, session_factory):
    user, headers = await make_user("fan@example.com")
    await activate(client, user.id)
    await send(client, event("evt_e", "subscription.expired", None, subscription_id="sub_1"))
    assert (await client.get(f"{API}/subscription", headers=headers)).json()["status"] == "expired"
    assert (await client.get(f"{API}/me/entitlements", headers=headers)).json()["premium"] is False

    other, _ = await make_user("other@example.com")
    await activate(client, other.id, event_id="evt_9", sub_id="sub_9", days=-30)  # lapsed long ago, never cleaned up
    async with session_factory() as db:
        assert await expire_lapsed_subscriptions_once(db) == 1
        assert await expire_lapsed_subscriptions_once(db) == 0  # idempotent
        statuses = {s.provider_subscription_id: s.status for s in (await db.execute(select(Subscription))).scalars()}
    assert statuses == {"sub_1": SubscriptionStatus.EXPIRED, "sub_9": SubscriptionStatus.EXPIRED}


async def test_entitlements_are_users_own_and_never_taken_from_the_client(client, make_user):
    a, ha = await make_user("a@example.com")
    b, hb = await make_user("b@example.com")
    await activate(client, a.id)
    assert (await client.get(f"{API}/me/entitlements", headers=hb)).json()["premium"] is False
    spoof = await client.get(f"{API}/me/entitlements?premium=true", headers={**hb, "X-Premium": "1", "X-Entitlements": "advanced_analytics"})
    assert spoof.json()["entitlements"] == []
    assert (await client.get(f"{API}/me/entitlements")).json()["entitlements"] == []  # anonymous


async def test_free_users_keep_the_core_football_experience(client, seeded_client):
    for path in ("/matches/live", "/matches/today", "/competitions", "/capabilities", "/search?q=ars"):
        assert (await client.get(f"{API}{path}")).status_code == 200, path


# -- ads ------------------------------------------------------------------------------------------------


async def test_ads_are_off_by_default_and_never_for_premium_or_live_matches(client, make_user, monkeypatch):
    off = (await client.get(f"{API}/ads/placements")).json()
    assert all(not p["eligible"] and p["reason"] == "ads are disabled" for p in off)
    monkeypatch.setattr(settings, "ads_enabled", True)
    free = {p["placement"]: p["eligible"] for p in (await client.get(f"{API}/ads/placements")).json()}
    assert free == {"home": True, "news": True, "match_centre": True}
    live = {p["placement"]: p["eligible"] for p in (await client.get(f"{API}/ads/placements?live=true")).json()}
    assert live["match_centre"] is False and live["home"] is True
    user, headers = await make_user("prem@example.com")
    await activate(client, user.id)
    premium = (await client.get(f"{API}/ads/placements", headers=headers)).json()
    assert all(not p["eligible"] and p["reason"] == "ad-free plan" for p in premium)


async def test_billing_metrics_are_counted(client, make_user):
    from app.services.metrics import metrics

    before = metrics.snapshot()
    user, _ = await make_user("fan@example.com")
    await activate(client, user.id)
    await send(client, b"{}", secret="wrong")
    after = metrics.snapshot()
    assert after["payment_webhooks_total"] == before["payment_webhooks_total"] + 1
    assert after["payment_webhooks_rejected_total"] == before["payment_webhooks_rejected_total"] + 1
    assert after["subscription_created_total"] == before["subscription_created_total"] + 1


# -- the Stripe adapter's parsing and production guards (no network) -----------------------------------------------


def _stripe(event_type, obj, event_id="evt_s1"):
    return json.dumps({"id": event_id, "type": event_type, "data": {"object": obj}}).encode()


def _parse_stripe(body):
    from app.services.billing.providers import StripeBillingProvider

    return StripeBillingProvider().parse_webhook(body, sign_payload(body, SECRET))


def test_stripe_events_are_normalised_to_the_app_vocabulary():
    activated = _parse_stripe(_stripe("checkout.session.completed", {"subscription": "sub_9", "customer": "cus_9", "client_reference_id": "42", "metadata": {"user_id": "42", "plan_code": "premium_yearly"}}))
    assert (activated.kind, activated.user_id, activated.plan_code, activated.subscription_id, activated.customer_id) == ("subscription.activated", 42, "premium_yearly", "sub_9", "cus_9")

    renewed = _parse_stripe(_stripe("customer.subscription.updated", {"id": "sub_9", "status": "active", "cancel_at_period_end": False, "current_period_end": 1900000000, "metadata": {}}))
    assert renewed.kind == "subscription.renewed" and renewed.period_end.year == 2030

    cancelled = _parse_stripe(_stripe("customer.subscription.updated", {"id": "sub_9", "status": "active", "cancel_at_period_end": True, "current_period_end": 1900000000}))
    assert cancelled.kind == "subscription.cancelled" and cancelled.cancel_at_period_end

    assert _parse_stripe(_stripe("customer.subscription.deleted", {"id": "sub_9"})).kind == "subscription.expired"
    failed = _parse_stripe(_stripe("invoice.payment_failed", {"subscription": "sub_9", "customer": "cus_9", "amount_due": 499, "currency": "gbp"}))
    assert (failed.kind, failed.subscription_id, failed.amount_minor) == ("payment.failed", "sub_9", 499)
    assert _parse_stripe(_stripe("customer.created", {"id": "cus_9"})).kind == "ignored"
    assert _parse_stripe(_stripe("customer.subscription.updated", {"id": "sub_9", "status": "past_due", "cancel_at_period_end": False})).kind == "ignored"


def test_stripe_rejects_unsigned_and_malformed_bodies():
    from app.services.billing.providers import StripeBillingProvider

    body = _stripe("invoice.payment_failed", {"subscription": "s"})
    with pytest.raises(InvalidSignature):
        StripeBillingProvider().parse_webhook(body, None)
    with pytest.raises(InvalidSignature):
        StripeBillingProvider().parse_webhook(b"not json", sign_payload(b"not json", SECRET))


def test_production_refuses_the_dev_secret_and_the_test_provider(monkeypatch):
    from app.services.billing.providers import ProviderError, get_billing_provider

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "billing_provider", "test")
    with pytest.raises(ProviderError):
        get_billing_provider()
    monkeypatch.setattr(settings, "billing_provider", "stripe")
    with pytest.raises(ProviderError):  # the default secret would make webhooks forgeable
        get_billing_provider()
    monkeypatch.setattr(settings, "billing_webhook_secret", "x" * 10)
    with pytest.raises(ProviderError):  # too short
        get_billing_provider()
    monkeypatch.setattr(settings, "billing_webhook_secret", "a-long-random-production-secret-value")
    assert get_billing_provider().name == "stripe"
    monkeypatch.setattr(settings, "billing_provider", "carrier-pigeon")
    with pytest.raises(ProviderError):
        get_billing_provider()


async def test_analytics_endpoints_are_rate_limited_per_client(client):
    statuses = [(await client.get(f"{API}/teams/999999/analytics")).status_code for _ in range(settings.analytics_per_minute + 1)]
    assert set(statuses[:-1]) == {404} and statuses[-1] == 429
