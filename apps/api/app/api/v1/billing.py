"""Subscription, entitlements, payment webhook and ad eligibility (Phase 6b).

The webhook is the only way a subscription becomes active: the checkout response
grants nothing. It is authenticated by an HMAC signature over the raw body (with a
replay window), idempotent on the processor's event id, and logged.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import BillingServiceDep, CurrentUserDep, EntitlementsDep, OptionalUserDep
from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.schemas.billing import (
    AdPlacementOut,
    CheckoutOut,
    CheckoutRequest,
    EntitlementsOut,
    FeatureOut,
    PlanOut,
    SubscriptionOut,
    WebhookAck,
)
from app.services import ads
from app.services.billing.entitlements import FEATURE_LABELS, PREMIUM_ENTITLEMENTS
from app.services.billing.providers import InvalidSignature
from app.services.billing.service import BillingError, summary_for
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

subscription_router = APIRouter()
webhook_router = APIRouter()
me_router = APIRouter()
ads_router = APIRouter()


@subscription_router.get("/plans", response_model=list[PlanOut])
async def plans(billing: BillingServiceDep) -> list[PlanOut]:
    rows = await billing.ensure_plans()
    await billing.db.commit()
    return [
        PlanOut(code=p.code, name=p.name, interval=p.interval, price_minor=p.price_minor, currency=p.currency, entitlements=list(p.entitlements))
        for p in sorted(rows, key=lambda p: p.price_minor)
    ]


@subscription_router.get("", response_model=SubscriptionOut)
async def my_subscription(user: CurrentUserDep, billing: BillingServiceDep) -> SubscriptionOut:
    return SubscriptionOut(**await summary_for(billing.db, user, billing))


@subscription_router.post(
    "/checkout",
    response_model=CheckoutOut,
    dependencies=[Depends(rate_limiter("checkout", settings.checkout_per_hour, 3600))],
)
async def checkout(payload: CheckoutRequest, user: CurrentUserDep, billing: BillingServiceDep) -> CheckoutOut:
    """Starts a hosted checkout. Nothing is granted until the processor's webhook confirms payment."""
    try:
        session = await billing.start_checkout(user, payload.plan_code)
        await billing.db.commit()
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return CheckoutOut(url=session.url, session_id=session.session_id)


@subscription_router.post("/cancel", response_model=SubscriptionOut)
async def cancel(user: CurrentUserDep, billing: BillingServiceDep) -> SubscriptionOut:
    """Cancels at the end of the paid period; Premium stays until then."""
    try:
        await billing.cancel(user)
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return SubscriptionOut(**await summary_for(billing.db, user, billing))


@me_router.get("/entitlements", response_model=EntitlementsOut)
async def my_entitlements(ents: EntitlementsDep) -> EntitlementsOut:
    """Informational for the UI. The server re-checks on every protected request."""
    return EntitlementsOut(
        entitlements=sorted(ents),
        premium=bool(ents),
        features=[FeatureOut(key=k, label=FEATURE_LABELS[k]) for k in PREMIUM_ENTITLEMENTS],
    )


@webhook_router.post(
    "/webhook",
    response_model=WebhookAck,
    dependencies=[Depends(rate_limiter("billing-webhook", settings.webhook_per_minute, 60))],
)
async def webhook(request: Request, billing: BillingServiceDep) -> WebhookAck:
    body = await request.body()
    if len(body) > 256 * 1024:
        raise HTTPException(status_code=413, detail="Payload too large")
    try:
        event = billing.provider.parse_webhook(body, request.headers.get("x-signature") or request.headers.get("stripe-signature"))
    except InvalidSignature as exc:
        metrics.count("payment_webhooks_rejected_total")
        logger.warning("billing webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid signature") from exc
    metrics.count("payment_webhooks_total")
    try:
        raw = json.loads(body)
    except ValueError:
        raw = {}
    outcome = await billing.handle_event(event, raw)
    if outcome == "failed":
        metrics.count("payment_webhooks_failed_total")
        raise HTTPException(status_code=500, detail="Event could not be processed; please retry")
    if outcome == "processed":
        await _notify(billing, event)
    return WebhookAck(result=outcome)  # type: ignore[arg-type]


async def _notify(billing, event) -> None:
    """Best effort: a notification problem must never make the processor retry a paid event."""
    try:
        from app.models.billing import Subscription
        from sqlalchemy import select

        user_id = event.user_id
        if user_id is None and event.subscription_id:
            user_id = (
                await billing.db.execute(
                    select(Subscription.user_id).where(
                        Subscription.provider == billing.provider.name,
                        Subscription.provider_subscription_id == event.subscription_id,
                    )
                )
            ).scalar_one_or_none()
        if user_id is not None:
            from app.worker.analytics_tasks import notify_subscription_event

            notify_subscription_event.delay(user_id, event.kind, event.event_id)
    except Exception:
        logger.warning("could not enqueue subscription notification", exc_info=True)


@ads_router.get("/placements", response_model=list[AdPlacementOut])
async def placements(ents: EntitlementsDep, user: OptionalUserDep, live: bool = False) -> list[AdPlacementOut]:
    """Which placements this viewer may show a slot in. No identifiers, no tracking."""
    return [AdPlacementOut(**vars(ads.eligibility(p, ents, live=live))) for p in ads.PLACEMENTS]
