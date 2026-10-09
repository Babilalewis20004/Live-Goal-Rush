"""Subscriptions and payment-webhook processing (Phase 6b)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import PaymentEvent, Subscription, SubscriptionPlan
from app.models.enums import PaymentEventStatus, SubscriptionStatus
from app.models.user import User
from app.services.billing.entitlements import PREMIUM_ENTITLEMENTS, entitlements_for, subscription_grants_access
from app.services.billing.providers import BillingEvent, BillingProvider, ProviderError
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

DEFAULT_PLANS = (
    dict(code="premium_monthly", name="Premium (monthly)", interval="month", price_minor=499, currency="GBP"),
    dict(code="premium_yearly", name="Premium (yearly)", interval="year", price_minor=3999, currency="GBP"),
)


class BillingError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class BillingService:
    def __init__(self, db: AsyncSession, provider: BillingProvider) -> None:
        self.db = db
        self.provider = provider

    # -- plans ---------------------------------------------------------------------

    async def ensure_plans(self) -> list[SubscriptionPlan]:
        """Plans are data; the defaults are created on first use (idempotent)."""
        existing = {p.code: p for p in (await self.db.execute(select(SubscriptionPlan))).scalars()}
        for spec in DEFAULT_PLANS:
            if spec["code"] not in existing:
                plan = SubscriptionPlan(entitlements=list(PREMIUM_ENTITLEMENTS), active=True, **spec)
                self.db.add(plan)
                existing[spec["code"]] = plan
        await self.db.flush()
        return [p for p in existing.values() if p.active]

    async def _plan(self, code: str) -> SubscriptionPlan:
        await self.ensure_plans()
        plan = (await self.db.execute(select(SubscriptionPlan).where(SubscriptionPlan.code == code))).scalar_one_or_none()
        if plan is None or not plan.active:
            raise BillingError("Unknown plan", 404)
        return plan

    # -- the user's subscription ---------------------------------------------------------

    async def current(self, user: User) -> tuple[Subscription, SubscriptionPlan] | None:
        """The newest subscription that is not simply over."""
        rows = (
            await self.db.execute(
                select(Subscription, SubscriptionPlan)
                .join(SubscriptionPlan, SubscriptionPlan.id == Subscription.plan_id)
                .where(Subscription.user_id == user.id, Subscription.status != SubscriptionStatus.INCOMPLETE)
                .order_by(Subscription.created_at.desc(), Subscription.id.desc())
            )
        ).all()
        for sub, plan in rows:
            if subscription_grants_access(sub):
                return sub, plan
        return (rows[0][0], rows[0][1]) if rows else None

    # -- checkout / cancel ------------------------------------------------------------

    async def start_checkout(self, user: User, plan_code: str):
        plan = await self._plan(plan_code)
        held = await self.current(user)
        if held is not None and subscription_grants_access(held[0]) and held[0].status != SubscriptionStatus.CANCELLED:
            raise BillingError("You already have an active subscription.", 409)
        try:
            return await self.provider.create_checkout(
                user_id=user.id, email=user.email, plan_code=plan.code, price_id=plan.provider_price_id
            )
        except ProviderError as exc:
            logger.warning("checkout failed provider=%s", self.provider.name, exc_info=True)
            raise BillingError(str(exc), 502) from exc

    async def cancel(self, user: User) -> Subscription:
        held = await self.current(user)
        if held is None or not subscription_grants_access(held[0]):
            raise BillingError("You have no active subscription.", 404)
        sub = held[0]
        if sub.status == SubscriptionStatus.CANCELLED:
            return sub  # idempotent
        if sub.provider_subscription_id:
            try:
                await self.provider.cancel_subscription(sub.provider_subscription_id)
            except ProviderError as exc:
                raise BillingError(str(exc), 502) from exc
        sub.status = SubscriptionStatus.CANCELLED
        sub.cancel_at_period_end = True
        await self.db.commit()
        metrics.count("subscription_cancelled_total")
        return sub

    # -- webhooks --------------------------------------------------------------------------

    async def handle_event(self, event: BillingEvent, raw: dict) -> str:
        """Apply one verified processor event. Returns "processed", "ignored", "duplicate" or "failed".

        Idempotent and retry-safe: the (provider, event_id) unique row is claimed
        first with INSERT .. ON CONFLICT DO NOTHING. A redelivery of an event that
        was already handled is acknowledged without touching anything; one that
        previously FAILED is retried. All effects commit atomically with the event row.
        """
        stmt = (
            pg_insert(PaymentEvent)
            .values(
                provider=self.provider.name,
                event_id=event.event_id,
                event_type=event.raw_type[:64],
                status=PaymentEventStatus.RECEIVED,
                payload=_sanitise(raw),
                attempts=1,
            )
            .on_conflict_do_nothing(constraint="uq_payment_events_provider_event")
            .returning(PaymentEvent.id)
        )
        claimed = (await self.db.execute(stmt)).scalar_one_or_none()
        if claimed is not None:
            row = await self.db.get(PaymentEvent, claimed)
        else:
            row = (
                await self.db.execute(
                    select(PaymentEvent)
                    .where(PaymentEvent.provider == self.provider.name, PaymentEvent.event_id == event.event_id)
                    .with_for_update()
                )
            ).scalar_one()
            if row.status in (PaymentEventStatus.PROCESSED, PaymentEventStatus.IGNORED):
                await self.db.rollback()
                return "duplicate"
            row.attempts += 1

        try:
            async with self.db.begin_nested():
                outcome = await self._apply(event)
            row.status = PaymentEventStatus.PROCESSED if outcome == "processed" else PaymentEventStatus.IGNORED
            row.error = None if outcome == "processed" else outcome[:300]
        except Exception as exc:  # recorded so it can be retried by the processor's redelivery
            logger.exception("payment event failed id=%s type=%s", event.event_id, event.raw_type)
            row.status = PaymentEventStatus.FAILED
            row.error = str(exc)[:300]
            row.processed_at = datetime.now(timezone.utc)
            await self.db.commit()  # keep the FAILED row; the processor will redeliver
            return "failed"
        row.processed_at = datetime.now(timezone.utc)
        await self.db.commit()
        return "processed" if row.status == PaymentEventStatus.PROCESSED else "ignored"

    async def _find(self, event: BillingEvent) -> Subscription | None:
        if event.subscription_id:
            sub = (
                await self.db.execute(
                    select(Subscription).where(
                        Subscription.provider == self.provider.name,
                        Subscription.provider_subscription_id == event.subscription_id,
                    )
                )
            ).scalar_one_or_none()
            if sub is not None:
                return sub
        return None

    async def _apply(self, event: BillingEvent) -> str:
        """Returns "processed" or a short reason it was ignored."""
        if event.kind == "ignored":
            return "unhandled event type"
        sub = await self._find(event)

        if event.kind == "subscription.activated":
            if event.user_id is None or not event.plan_code:
                return "missing user or plan"
            user = await self.db.get(User, event.user_id)
            if user is None:
                return "unknown user"
            plan = await self._plan(event.plan_code)
            if sub is None:
                sub = Subscription(
                    user_id=user.id, plan_id=plan.id, status=SubscriptionStatus.ACTIVE, provider=self.provider.name,
                    provider_subscription_id=event.subscription_id, provider_customer_id=event.customer_id,
                    current_period_end=event.period_end, cancel_at_period_end=False, last_event_at=event.occurred_at,
                )
                self.db.add(sub)
                metrics.count("subscription_created_total")
            else:
                if event.occurred_at is not None and sub.last_event_at is not None and event.occurred_at < sub.last_event_at:
                    metrics.count("payment_webhooks_stale_total")
                    return "stale event"
                sub.status, sub.plan_id, sub.cancel_at_period_end = SubscriptionStatus.ACTIVE, plan.id, False
                sub.current_period_end = _later(sub.current_period_end, event.period_end)
                if event.occurred_at is not None:
                    sub.last_event_at = event.occurred_at
            return "processed"

        if sub is None:
            return "unknown subscription"  # e.g. an event for a subscription we never activated

        # Deliveries are unordered: a retried or delayed older event must not undo a newer one (a late
        # "cancelled" switching off auto-renew after a renewal, a late "failed" invoice, an old period end
        # shortening a paid period). Events without a timestamp are applied as they arrive.
        if event.occurred_at is not None and sub.last_event_at is not None and event.occurred_at < sub.last_event_at:
            metrics.count("payment_webhooks_stale_total")
            return "stale event"
        if event.occurred_at is not None:
            sub.last_event_at = event.occurred_at

        if event.kind == "subscription.renewed":
            sub.status = SubscriptionStatus.ACTIVE
            sub.current_period_end = _later(sub.current_period_end, event.period_end)
            sub.cancel_at_period_end = False
            metrics.count("subscription_renewed_total")
        elif event.kind == "subscription.cancelled":
            sub.status = SubscriptionStatus.CANCELLED
            sub.cancel_at_period_end = True
            sub.current_period_end = event.period_end or sub.current_period_end
        elif event.kind == "subscription.expired":
            sub.status = SubscriptionStatus.EXPIRED
        elif event.kind == "payment.failed":
            if sub.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE):
                sub.status = SubscriptionStatus.PAST_DUE
            metrics.count("subscription_payment_failed_total")
        else:
            return "unhandled event kind"
        return "processed"


def _later(current: datetime | None, incoming: datetime | None) -> datetime | None:
    """A paid period only ever grows: an out-of-date period end never shortens it."""
    if incoming is None:
        return current
    if current is None:
        return incoming
    return max(current, incoming)


_KEEP = {"id", "type", "created", "livemode"}


def _sanitise(raw: dict) -> dict:
    """Keep the audit trail useful but small and card-free: event identity plus ids/amounts."""
    out = {k: v for k, v in raw.items() if k in _KEEP}
    data = raw.get("data") or {}
    obj = data.get("object") if isinstance(data, dict) and "object" in data else data
    if isinstance(obj, dict):
        safe = {
            k: obj[k]
            for k in ("id", "status", "subscription", "customer", "user_id", "plan_code", "subscription_id", "customer_id",
                      "period_end", "current_period_end", "cancel_at_period_end", "amount_due", "amount_minor", "currency")
            if k in obj
        }
        out["object"] = safe
    return out


async def summary_for(db: AsyncSession, user: User, billing: BillingService) -> dict:
    held = await billing.current(user)
    ents = sorted(await entitlements_for(db, user))
    if held is None:
        return {"status": "none", "plan": None, "entitlements": ents, "current_period_end": None, "cancel_at_period_end": False}
    sub, plan = held
    return {
        "status": sub.status.value,
        "plan": plan.code,
        "entitlements": ents,
        "current_period_end": sub.current_period_end,
        "cancel_at_period_end": sub.cancel_at_period_end,
    }
