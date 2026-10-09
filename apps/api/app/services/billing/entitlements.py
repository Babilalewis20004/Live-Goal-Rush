"""What a user is allowed to use (Phase 6b).

Entitlements are plain string keys. A user's effective set is computed on every
request from the database -- deliberately not cached, so a cancellation, expiry
or refund takes effect immediately and stale premium access cannot leak from a
cache. (Two small indexed queries; the expensive data they guard is cached
separately and is *shaped* per tier after the cache, never stored per user.)

Free users keep everything a football fan needs day to day: livescores, the
match centre, standings, news, search, favourites, notifications and community.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.billing import Entitlement, Subscription, SubscriptionPlan
from app.models.enums import SubscriptionStatus
from app.models.user import User

ADVANCED_ANALYTICS = "advanced_analytics"
EXTENDED_HISTORY = "extended_history"
ADVANCED_COMPARISON = "advanced_comparison"
PREDICTION_DETAILS = "prediction_details"
PLAYER_ANALYTICS = "player_analytics"
AD_FREE = "ad_free"

PREMIUM_ENTITLEMENTS: tuple[str, ...] = (
    ADVANCED_ANALYTICS,
    EXTENDED_HISTORY,
    ADVANCED_COMPARISON,
    PREDICTION_DETAILS,
    PLAYER_ANALYTICS,
    AD_FREE,
)
ALL_ENTITLEMENTS = frozenset(PREMIUM_ENTITLEMENTS)

FEATURE_LABELS = {
    ADVANCED_ANALYTICS: "Advanced team analytics",
    EXTENDED_HISTORY: "Extended head-to-head and form history",
    ADVANCED_COMPARISON: "Full match comparison",
    PREDICTION_DETAILS: "Detailed prediction breakdown",
    PLAYER_ANALYTICS: "Advanced player analytics",
    AD_FREE: "Ad-free experience",
}


def subscription_grants_access(sub: Subscription, now: datetime | None = None) -> bool:
    """Does this subscription currently entitle its owner?

    * ACTIVE: until the paid period ends, plus a grace window so a delayed
      renewal webhook does not cut a paying user off.
    * PAST_DUE: a renewal failed; the same grace window applies, then access stops.
    * CANCELLED: the user cancelled; access runs to the end of the period they paid for.
    * INCOMPLETE / EXPIRED: never.
    """
    now = now or datetime.now(timezone.utc)
    grace = timedelta(days=settings.billing_grace_days)
    end = sub.current_period_end
    if sub.status in (SubscriptionStatus.INCOMPLETE, SubscriptionStatus.EXPIRED):
        return False
    if sub.status == SubscriptionStatus.CANCELLED:
        return end is not None and end > now
    if sub.status == SubscriptionStatus.ACTIVE:
        return end is None or end + grace > now
    if sub.status == SubscriptionStatus.PAST_DUE:
        return end is not None and end + grace > now
    return False


async def entitlements_for(db: AsyncSession, user: User | None) -> frozenset[str]:
    if user is None:
        return frozenset()
    now = datetime.now(timezone.utc)
    granted: set[str] = set()
    rows = (
        await db.execute(
            select(Subscription, SubscriptionPlan)
            .join(SubscriptionPlan, SubscriptionPlan.id == Subscription.plan_id)
            .where(Subscription.user_id == user.id)
        )
    ).all()
    for sub, plan in rows:
        if subscription_grants_access(sub, now):
            granted.update(plan.entitlements or [])
    grants = (
        await db.execute(
            select(Entitlement.key).where(
                Entitlement.user_id == user.id, (Entitlement.expires_at.is_(None)) | (Entitlement.expires_at > now)
            )
        )
    ).scalars()
    granted.update(grants)
    return frozenset(granted & ALL_ENTITLEMENTS)


async def has_entitlement(db: AsyncSession, user: User | None, key: str) -> bool:
    return key in await entitlements_for(db, user)


def payment_required(key: str) -> HTTPException:
    """402 with the missing entitlement named, so clients can show the right upsell."""
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={"message": f"{FEATURE_LABELS.get(key, key)} is a Premium feature.", "entitlement": key},
    )
